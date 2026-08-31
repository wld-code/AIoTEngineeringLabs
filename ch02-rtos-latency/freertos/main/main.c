// Lab 2 — FreeRTOS task-based port of the same workload as superloop/.
// Three worker tasks + a reporter, queue-driven alarm.
//
// SELF-MEASURING: same two metrics as the superloop build, printed over the
// USB serial monitor.
//   1. worst-case alarm latency — alarm_task is the highest-priority worker,
//      so it can pre-empt the lower-priority telemetry task instead of
//      waiting behind it.
//   2. CPU idle time — every task blocks (vTaskDelay / queue receive)
//      between chores, so the idle task gets to run. See README for what
//      this idle time does and does not imply about power consumption.
//
// Build: pio run -t upload (or idf.py set-target esp32s3 && idf.py build flash monitor)
// Target: Seeed Studio XIAO ESP32-S3 + its USB-C cable.

#include <inttypes.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#define GPIO_ALARM         GPIO_NUM_2    // optional: hang an LED on D1 to see alarms
#define TEMP_THRESHOLD_C   80
#define EVENT_PERIOD_US    (500 * 1000)  // alarm event every 500 ms
#define ACQUIRE_PERIOD_MS  100           // sensor read every 100 ms
#define BLOCKING_SEND_US   (40 * 1000)   // telemetry operation blocks for 40 ms
#define TELEMETRY_PERIOD_MS 5000         // telemetry operation every 5 s
                                          // Part 3 (incorrect priority assignment): change to 50.
#define REPORT_PERIOD_MS   5000          // print a report every 5 s

// EVENT_PERIOD_US divides TELEMETRY_PERIOD_MS exactly (500 ms x 10 = 5 s).
// See superloop/main/main.c for why that phase-locks the two schedules
// together on this hardware. telemetry_task's very first cycle is
// scheduled 20 ms early so the workload matches the superloop build.
#define TELEMETRY_PHASE_LEAD_MS 20

static const char *TAG = "freertos";
static QueueHandle_t alarm_queue;   // carries the event timestamp (int64_t us)

// One spinlock guards every value shared across tasks: the latest
// temperature (written by acquire_task, read by telemetry_task) and the
// report counters (written by alarm_task, read by report_task). The
// critical sections are a handful of instructions each, so a single mutex
// is simpler than one per variable and costs nothing extra here. int64_t is
// not guaranteed atomic on Xtensa, and `volatile` alone would not prevent a
// torn read, so a real critical section is the correct minimum — not just
// a style choice.
static portMUX_TYPE g_shared_mux = portMUX_INITIALIZER_UNLOCKED;
static int      g_latest_temp_c    = 25;
static int64_t  g_worst_latency_us = 0;
static uint32_t g_events_seen      = 0;

static int read_temperature_c(void) {
    static int t = 25;
    t = (t + 1) % 100;
    return t;
}

// Periodic esp_timer callback. With the default ESP-IDF dispatch method,
// this runs from the high-priority "esp_timer" task and hands the
// timestamp to alarm_task over a queue. This is not an ISR and not a
// hardware-timer interrupt — see README for what that would change.
static void event_timer_cb(void *arg) {
    int64_t now = esp_timer_get_time();
    xQueueSend(alarm_queue, &now, 0);
}

// Priority 5 — reads the sensor every 100 ms and publishes the result for
// telemetry_task to pick up. vTaskDelayUntil keeps the 100 ms period stable
// even if a run takes a few microseconds longer than the last.
static void acquire_task(void *arg) {
    TickType_t last_wake = xTaskGetTickCount();
    while (1) {
        int t = read_temperature_c();
        portENTER_CRITICAL(&g_shared_mux);
        g_latest_temp_c = t;
        portEXIT_CRITICAL(&g_shared_mux);
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(ACQUIRE_PERIOD_MS));
    }
}

// Priority 7 — blocks on the queue and reacts as soon as an event arrives,
// so it can pre-empt whatever telemetry_task is doing.
static void alarm_task(void *arg) {
    int64_t event_us;
    while (1) {
        if (xQueueReceive(alarm_queue, &event_us, portMAX_DELAY) == pdTRUE) {
            int64_t latency_us = esp_timer_get_time() - event_us;
            portENTER_CRITICAL(&g_shared_mux);
            g_events_seen++;
            if (latency_us > g_worst_latency_us) g_worst_latency_us = latency_us;
            portEXIT_CRITICAL(&g_shared_mux);
            gpio_set_level(GPIO_ALARM, 1);
            gpio_set_level(GPIO_ALARM, 0);
        }
    }
}

// Priority 3 — every TELEMETRY_PERIOD_MS, reads the latest temperature
// acquire_task published and runs the same blocking 40 ms operation the
// superloop build runs. It does not call read_temperature_c() itself: both
// builds must acquire from the same place so the workload stays identical.
static void telemetry_task(void *arg) {
    TickType_t last_wake = xTaskGetTickCount();
    // First cycle only: open TELEMETRY_PHASE_LEAD_MS early (see the
    // #define above) so this task's schedule isn't phase-locked to the
    // alarm timer's from boot. Every following cycle is a normal
    // TELEMETRY_PERIOD_MS tick from there.
    vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(TELEMETRY_PERIOD_MS - TELEMETRY_PHASE_LEAD_MS));
    while (1) {
        portENTER_CRITICAL(&g_shared_mux);
        int t = g_latest_temp_c;
        portEXIT_CRITICAL(&g_shared_mux);

        int64_t end = esp_timer_get_time() + BLOCKING_SEND_US;
        while (esp_timer_get_time() < end) { /* blocking send */ }
        ESP_LOGI(TAG, "telemetry t=%dC", t);

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(TELEMETRY_PERIOD_MS));
    }
}

static float idle_percent_since_last(void) {
    // ulTaskGetIdleRunTimeCounter() reports run time in the esp_timer
    // microsecond clock. CONFIG_FREERTOS_UNICORE=y (see sdkconfig.defaults)
    // keeps this a single, unambiguous counter for one core.
    static uint32_t last_idle_us = 0;
    static int64_t  last_wall_us = 0;
    uint32_t idle_us = ulTaskGetIdleRunTimeCounter();
    int64_t  wall_us = esp_timer_get_time();
    uint32_t d_idle = idle_us - last_idle_us;
    int64_t  d_wall = wall_us - last_wall_us;
    last_idle_us = idle_us;
    last_wall_us = wall_us;
    if (d_wall <= 0) return 0.0f;
    float pct = 100.0f * (float)d_idle / (float)d_wall;
    return pct > 100.0f ? 100.0f : pct;
}

// Priority 10 (highest) — prints the report every 5 s, then blocks. Kept
// above the workers so it always gets to print, including in Part 3.
static void report_task(void *arg) {
    (void)idle_percent_since_last();  // prime the counters
    TickType_t last_wake = xTaskGetTickCount();
    while (1) {
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(REPORT_PERIOD_MS));
        float idle = idle_percent_since_last();
        portENTER_CRITICAL(&g_shared_mux);
        uint32_t events   = g_events_seen;
        int64_t  worst_us = g_worst_latency_us;
        portEXIT_CRITICAL(&g_shared_mux);
        ESP_LOGW(TAG,
                 "REPORT  events=%" PRIu32 "  worst_latency=%" PRId64
                 " us (%.3f ms)  cpu_idle=%.1f%%",
                 events, worst_us, worst_us / 1000.0, idle);
    }
}

void app_main(void) {
    nvs_flash_init();
    gpio_set_direction(GPIO_ALARM, GPIO_MODE_OUTPUT);
    gpio_set_level(GPIO_ALARM, 0);

    alarm_queue = xQueueCreate(8, sizeof(int64_t));

    const esp_timer_create_args_t targs = {
        .callback = event_timer_cb, .name = "event"};
    esp_timer_handle_t event_timer;
    ESP_ERROR_CHECK(esp_timer_create(&targs, &event_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(event_timer, EVENT_PERIOD_US));

    ESP_LOGW(TAG, "FreeRTOS build running — tasks block, idle task runs");

    // Part 3 (incorrect priority assignment): change alarm_task's priority
    // 7 -> 1, telemetry_task's priority 3 -> 9, and TELEMETRY_PERIOD_MS
    // above 5000 -> 50. That makes telemetry_task run frequently at a
    // higher priority than alarm_task, delaying alarm processing during
    // its busy periods. Revert all three before moving on.
    xTaskCreate(acquire_task,   "acquire",   4096, NULL, 5, NULL);
    xTaskCreate(alarm_task,     "alarm",     4096, NULL, 7, NULL);
    xTaskCreate(telemetry_task, "telemetry", 4096, NULL, 3, NULL);
    xTaskCreate(report_task,    "report",    4096, NULL, 10, NULL);
}
