import fs from "fs";
const { bytesToProblems } = await import("../../app/src/main/assets/www/js/sgfimport.js");
const sort = (o) => Array.isArray(o) ? o.map(sort) : o && typeof o === "object" ? Object.fromEntries(Object.keys(o).sort().map((k) => [k, sort(o[k])])) : o;
console.log(JSON.stringify(sort(process.argv.slice(2).map((f) => bytesToProblems(new Uint8Array(fs.readFileSync(f)), 1000, 1, "imp")))));
