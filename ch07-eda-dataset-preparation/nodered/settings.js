// Lab 7 — minimal Node-RED settings, scoped to this lab folder.
//
// userDir is this folder itself, not the usual ~/.node-red, so the flow and
// its node_modules stay inside the lab and never collide with a Node-RED
// instance you already run for something else, or with Lab 6's.

module.exports = {
    uiPort: process.env.PORT || 1880,
    userDir: __dirname,
    flowFile: "flows.json",
    flowFilePretty: true,
    editorTheme: {
        projects: { enabled: false },
    },
};
