// Lab 2 — polling super-loop, run under ESP-IDF/FreeRTOS.
//
// This is NOT a bare-metal application: it links against FreeRTOS (via
// app_main) and uses ulTaskGetIdleRunTimeCounter() for its idle-time metric.
// What makes it a "polling super-loop" is its own control flow: a single
// while(1) that checks each chore in turn and never calls vTaskDelay(),
// never yields, never sleeps. Part 2 (freertos/) runs the identical workload
// split across pre-emptible tasks — that's the comparison this lab makes:
// polling super-loop vs FreeRTOS task-based scheduling, not "bare metal vs
// FreeRTOS".
//
// WORKLOAD MATCHES THE FREERTOS BUILD: acquire every 100 ms, a 40 ms
// blocking telemetry operation every 5 s, an alarm event every 500 ms.
// Only the scheduling model differs, so any difference in the results is
// attributable to that.
//
// SELF-MEASURING: everything needed is printed over the USB serial monitor.
//   1. worst-case alarm latency, measured with esp_timer (microsecond clock).
//   2. CPU idle time, from ulTaskGetIdleRunTimeCounter() — how much time the
//      idle task got to run, not a direct power measurement (see README).
//
// Build: pio run -t upload (or idf.py set-target esp32s3 && idf.py build flash monitor)
// Target: Seeed Studio XIAO ESP32-S3 + its USB-C cable.

#include <inttypes.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#define GPIO_ALARM          GPIO_NUM_2    // optional: hang an LED on D1 to see alarms
#define TEMP_THRESHOLD_C    80
#define EVENT_PERIOD_US     (500 * 1000)     // alarm event every 500 ms
#define ACQUIRE_PERIOD_US   (100 * 1000)     // sensor read every 100 ms
#define TELEMETRY_PERIOD_US (5 * 1000000)    // telemetry operation every 5 s
#define BLOCKING_SEND_US    (40 * 1000)      // telemetry operation blocks for 40 ms
#define REPORT_PERIOD_US    (5 * 1000000)    // print a report every 5 s

// EVENT_PERIOD_US divides TELEMETRY_PERIOD_US exactly (500 ms x 10 = 5 s).
// Starting both schedules from the same boot-time reference would therefore
// lock every alarm tick to the same fixed offset from every telemetry
// window, forever - on this hardware both timers share one clock source, so
// there is no independent jitter to walk that phase apart at run time. That
// makes the two schedules either always miss or always meet, never
// "occasionally by chance". Opening the first telemetry window 20 ms before
// an alarm tick is due makes them meet on every cycle instead of relying on
// coincidence.
#define TELEMETRY_PHASE_LEAD_US (20 * 1000)

static const char *TAG = "superloop";

// Written by the periodic esp_timer callback, read by the main loop. Both
// sides are plain word-sized accesses on a single core, so a lost or torn
// read here is not a realistic failure mode — see README for the general
// rule on when that stops being true.
static volatile int64_t g_event_us      = 0;
static volatile bool    g_event_pending = false;

// Single-writer, single-reader: only the main loop ever touches these, so no
// synchronization is needed here (contrast with the FreeRTOS build, where
// the same counters are written by one task and read by another).
static int64_t  g_worst_latency_us = 0;
static uint32_t g_events_seen      = 0;

static int read_temperature_c(void) {
    // Stub: in the real lab, read an SHT4x or NTC. Here we simulate a ramp.
    static int t = 25;
    t = (t + 1) % 100;
    return t;
}

// Simulates a blocking send: it burns CPU for BLOCKING_SEND_US and never
// yields. This is what the alarm has to wait behind if it fires during
// this window.
static void send_telemetry_blocking(int t) {
    int64_t end = esp_timer_get_time() + BLOCKING_SEND_US;
    while (esp_timer_get_time() < end) {
        // spin — no yield, no sleep
    }
    ESP_LOGI(TAG, "telemetry t=%dC", t);
}

// Periodic esp_timer callback. With the default ESP-IDF dispatch method,
// this runs from the high-priority "esp_timer" task, so it fires close to
// its scheduled time even while the main loop is busy. It only records a
// timestamp; the loop is responsible for reacting to it. This is not an ISR
// and not a hardware-timer interrupt — see README for what that would change.
static void event_timer_cb(void *arg) {
    g_event_us      = esp_timer_get_time();
    g_event_pending = true;
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

void app_main(void) {
    nvs_flash_init();
    gpio_set_direction(GPIO_ALARM, GPIO_MODE_OUTPUT);
    gpio_set_level(GPIO_ALARM, 0);

    const esp_timer_create_args_t targs = {
        .callback = event_timer_cb, .name = "event"};
    esp_timer_handle_t event_timer;
    ESP_ERROR_CHECK(esp_timer_create(&targs, &event_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(event_timer, EVENT_PERIOD_US));

    ESP_LOGW(TAG, "polling super-loop running — it does not sleep");
    (void)idle_percent_since_last();  // prime the counters

    int64_t now = esp_timer_get_time();
    int64_t next_acquire   = now + ACQUIRE_PERIOD_US;
    int64_t next_telemetry = now + TELEMETRY_PERIOD_US - TELEMETRY_PHASE_LEAD_US;
    int64_t next_report    = now + REPORT_PERIOD_US;
    int last_t = 25;

    while (1) {
        now = esp_timer_get_time();

        // Checked on every spin, so latency is bounded only by whatever
        // chore the loop happens to be inside of when the event arrives.
        if (g_event_pending) {
            int64_t latency_us = esp_timer_get_time() - g_event_us;
            g_event_pending = false;
            g_events_seen++;
            if (latency_us > g_worst_latency_us) g_worst_latency_us = latency_us;
            gpio_set_level(GPIO_ALARM, last_t > TEMP_THRESHOLD_C ? 1 : 0);
        }

        if (now >= next_acquire) {
            last_t = read_temperature_c();
            next_acquire += ACQUIRE_PERIOD_US;
        }

        if (now >= next_telemetry) {
            send_telemetry_blocking(last_t);
            next_telemetry += TELEMETRY_PERIOD_US;
        }

        if (now >= next_report) {
            float idle = idle_percent_since_last();
            ESP_LOGW(TAG,
                     "REPORT  events=%" PRIu32 "  worst_latency=%" PRId64
                     " us (%.1f ms)  cpu_idle=%.1f%%",
                     g_events_seen, g_worst_latency_us,
                     g_worst_latency_us / 1000.0, idle);
            next_report += REPORT_PERIOD_US;
        }
        // No vTaskDelay, no yield, no sleep: between chores the loop just
        // re-checks the three conditions above. That busy-poll, not the
        // telemetry operation, is what keeps cpu_idle near 0 % below.
    }
}
