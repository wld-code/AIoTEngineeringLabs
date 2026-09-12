// Lab 6 — minimal Node-RED settings, scoped to this lab folder.
//
// userDir is this folder itself, not the usual ~/.node-red, so the flow,
// its credentials, and its node_modules all stay inside the lab and never
// collide with a Node-RED instance you already run for something else.

module.exports = {
    uiPort: process.env.PORT || 1880,
    userDir: __dirname,
    flowFile: "flows.json",
    flowFilePretty: true,
    editorTheme: {
        projects: { enabled: false },
    },
};
