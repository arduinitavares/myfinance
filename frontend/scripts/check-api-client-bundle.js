const fs = require('fs');
const path = require('path');

const buildJsDirectory = path.join(__dirname, '..', 'build', 'static', 'js');

if (!fs.existsSync(buildJsDirectory)) {
  throw new Error(
    `Build output not found at ${buildJsDirectory}. Run "npm run build" before "npm run check:bundle".`
  );
}

const jsAssets = fs
  .readdirSync(buildJsDirectory)
  .filter((fileName) => fileName.endsWith('.js'))
  .sort((left, right) => left.localeCompare(right));

if (jsAssets.length === 0) {
  throw new Error(`No built .js assets found in ${buildJsDirectory}.`);
}

for (const assetName of jsAssets) {
  const assetPath = path.join(buildJsDirectory, assetName);
  const assetContents = fs.readFileSync(assetPath, 'utf8');

  if (assetContents.includes('static/media/axios')) {
    throw new Error(
      `Bundle regression detected in ${assetName}: found "static/media/axios", which means axios was emitted as an asset instead of being bundled for runtime use.`
    );
  }
}

console.log(
  `Bundle check passed: ${jsAssets.length} built JS asset(s) do not reference static/media/axios`
);
