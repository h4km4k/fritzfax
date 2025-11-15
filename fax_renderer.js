// fax_renderer.js
const { createCanvas, loadImage } = require('canvas');
const SFF = require('./sffcoder.js');
const fs = require('fs');

function textToSFF(text) {
    const canvasWidth = 1728;
    const canvasHeight = 2444;
    const canvas = createCanvas(canvasWidth, canvasHeight);
    const ctx = canvas.getContext('2d');

    // Hintergrund weiß
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvasWidth, canvasHeight);

    // Text in schwarz
    ctx.fillStyle = 'black';
    ctx.font = '20px Arial';
    ctx.fillText(text, 50, 50);

    const sff = new SFF();
    const sffData = sff.Canvas2SFF([canvas]);
    return Buffer.from(sffData).toString('base64');
}

async function imageToSFF(imagePath) {
    const img = await loadImage(imagePath);

    const canvasWidth = 1728;
    const canvasHeight = 2444;
    const canvas = createCanvas(canvasWidth, canvasHeight);
    const ctx = canvas.getContext('2d');

    // Hintergrund weiß
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvasWidth, canvasHeight);

    // Proportionale Skalierung
    const imgAspect = img.width / img.height;
    const canvasAspect = canvasWidth / canvasHeight;

    let drawWidth, drawHeight;
    if (imgAspect > canvasAspect) {
        drawWidth = canvasWidth;
        drawHeight = canvasWidth / imgAspect;
    } else {
        drawHeight = canvasHeight;
        drawWidth = canvasHeight * imgAspect;
    }

    const offsetX = (canvasWidth - drawWidth) / 2;
    const offsetY = (canvasHeight - drawHeight) / 2;

    ctx.drawImage(img, offsetX, offsetY, drawWidth, drawHeight);

    const sff = new SFF();
    const sffData = sff.Canvas2SFF([canvas]);
    return Buffer.from(sffData).toString('base64');
}

// CLI
if (require.main === module) {
    const arg = process.argv[2];
    if (!arg) {
        console.error("Usage: node fax_renderer.js <text-or-image>");
        process.exit(1);
    }

    // Prüfen, ob es ein Bildpfad ist
    const imgExts = ['.png', '.jpg', '.jpeg', '.bmp'];
    if (imgExts.some(ext => arg.toLowerCase().endsWith(ext))) {
        // Bildverarbeitung
        imageToSFF(arg)
            .then(b64 => console.log(b64))
            .catch(err => {
                console.error("Error converting image to SFF:", err);
                process.exit(1);
            });
    } else {
        // Textverarbeitung
        const sffB64 = textToSFF(arg);
        console.log(sffB64);
    }
}

// Export für Python subprocess
module.exports = { textToSFF, imageToSFF };
