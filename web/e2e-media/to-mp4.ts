// Convierte las tomas WebM de <MEDIA_DIR>/video a MP4 H.264 (30 fps, yuv420p) en <MEDIA_DIR>/mp4, arma la
// escena 3 completa (portugués + inyección) y lista las duraciones. Requiere ffmpeg (FFMPEG=ruta o en el PATH).
//   node e2e-media/to-mp4.ts        (Node ≥ 22.18/23.6 ejecuta TypeScript sin compilar)
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const mediaDir = process.env.MEDIA_DIR ?? path.resolve(here, "..", "..", "data", "media");
const ffmpeg = process.env.FFMPEG ?? "ffmpeg";
const videoDir = path.join(mediaDir, "video");
const mp4Dir = path.join(mediaDir, "mp4");
mkdirSync(mp4Dir, { recursive: true });

const run = (args: string[]) => execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", ...args]);

for (const file of readdirSync(videoDir).filter((f) => f.endsWith(".webm"))) {
  const out = path.join(mp4Dir, file.replace(/\.webm$/, ".mp4"));
  run([
    ...["-i", path.join(videoDir, file), "-r", "30", "-c:v", "libx264", "-preset", "slow", "-crf", "18"],
    ...["-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
  ]);
  console.log(`ok ${out}`);
}

// Escena 3 del guion = handoff en portugués + inyección bloqueada, en una sola toma.
const parts = ["escena3a_fraude_pt.mp4", "escena3b_inyeccion.mp4"].map((f) => path.join(mp4Dir, f));
const list = path.join(mp4Dir, "concat.txt");
writeFileSync(list, parts.map((p) => `file '${p.replaceAll("\\", "/")}'`).join("\n"));
try {
  run([
    "-f",
    "concat",
    "-safe",
    "0",
    "-i",
    list,
    "-c",
    "copy",
    path.join(mp4Dir, "escena3_pt_e_inyeccion.mp4"),
  ]);
} finally {
  unlinkSync(list);
}

// Duraciones (ffmpeg -i imprime "Duration: hh:mm:ss.cc" en stderr y sale con código 1 sin salida).
for (const file of readdirSync(mp4Dir).filter((f) => f.endsWith(".mp4"))) {
  let info = "";
  try {
    execFileSync(ffmpeg, ["-hide_banner", "-i", path.join(mp4Dir, file)], { stdio: "pipe" });
  } catch (e) {
    info = String((e as { stderr?: Buffer }).stderr ?? "");
  }
  console.log(`${file}\t${/Duration: (\S+),/.exec(info)?.[1] ?? "?"}`);
}
