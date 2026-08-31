// Lab 5 — minimal Node-RED settings. Trimmed to what this lab actually
// needs; see https://nodered.org/docs/user-guide/runtime/configuration for
// the full set of options this omits.
module.exports = {
    // Load flows.json automatically on startup — this is what makes
    // `docker compose up --build` work with no manual flow import.
    flowFile: "flows.json",
    flowFilePretty: true,

    uiPort: process.env.PORT || 1880,

    logging: {
        console: {
            level: "info",
            metrics: false,
            audit: false,
        },
    },

    // Function nodes in flows.json don't need extra npm modules, but leave
    // this on so the editor's Function node still offers the option.
    functionExternalModules: true,
};
