const { greet } = require("../foo");
const dyn = import("../bar");

module.exports = { greet, dyn };
