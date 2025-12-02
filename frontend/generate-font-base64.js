const fs = require("fs");
const path = require("path");

// Target folder containing font files
const fontsDir = path.join(__dirname, "static");

// Collect loader lines
let loaderLines = [];
loaderLines.push("// Auto-generated font loader");
loaderLines.push("export function loadFonts(doc) {");

// Read all files in the folder
fs.readdirSync(fontsDir).forEach(file => {
    const fullPath = path.join(fontsDir, file);

    // Process only .ttf files
    if (fs.statSync(fullPath).isFile() && path.extname(file).toLowerCase() === ".ttf") {
        const fontFileName = path.basename(file, ".ttf"); // e.g. NotoSansHebrew-Bold

        // Split family and style
        let family = fontFileName;
        let style = "normal";

        const hyphenIndex = fontFileName.lastIndexOf("-");
        const underscoreIndex = fontFileName.lastIndexOf("_");
        const splitIndex = Math.max(hyphenIndex, underscoreIndex);

        if (splitIndex > 0) {
            family = fontFileName.substring(0, splitIndex);
            style = fontFileName.substring(splitIndex + 1).toLowerCase();
        }

        const outputDir = path.join(fontsDir, family);

        // Create family folder if it doesn't exist
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir);
        }

        // Read and encode font
        const fontData = fs.readFileSync(fullPath);
        const base64 = fontData.toString("base64").replace(/\s+/g, "");

        // Save to file named by style
        const outputFile = path.join(outputDir, `${style}.txt`);
        fs.writeFileSync(outputFile, base64);

        console.log(`✅ Saved Base64 for ${file} → ${outputFile}`);

        // Add loader line
        loaderLines.push(`  doc.addFileToVFS("${fontFileName}.ttf", \`${base64}\`);`);
        loaderLines.push(`  doc.addFont("${fontFileName}.ttf", "${family}", "${style}");`);
    }
});

loaderLines.push("}");

// Write loader file
const loaderFile = path.join(fontsDir, "..", "font-loader.js");
fs.writeFileSync(loaderFile, loaderLines.join("\n"), "utf8");

console.log(`✅ Font loader created at ${loaderFile}`);
