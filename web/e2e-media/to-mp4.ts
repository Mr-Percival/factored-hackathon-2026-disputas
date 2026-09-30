// Convierte las tomas WebM de <MEDIA_DIR>/video a MP4 H.264 (30 fps, yuv420p) en <MEDIA_DIR>/mp4, arma la
// escena 3 completa (portugués + inyección, ≤ 40 s) y lista las duraciones. Requiere ffmpeg (FFMPEG=ruta o PATH).
//   node e2e-media/to-mp4.ts        (Node ≥ 22.18/23.6 ejecuta TypeScript sin compilar)
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const mediaDir = process.env.MEDIA_DIR ?? path.resolve(here, "..", "..", "data", "media");
const ffmpeg = process.env.FFMPEG ?? "ffmpeg";
const videoDir = path.join(mediaDir, "video");
const mp4Dir = path.join(mediaDir, "mp4");
const LEAD = Number(process.env.MEDIA_LEAD_TRIM ?? 1.0); // la carga inicial de la página (cuadros en blanco)
const SCENE3_MAX = 40; // tope del guion para la escena 3 (2:00–2:40)
mkdirSync(mp4Dir, { recursive: true });

const run = (args: string[]) => execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", ...args]);
const H264 = ["-r", "30", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"];

/** Duración en segundos (ffmpeg -i la imprime en stderr y sale con código 1). */
function duration(file: string): number {
  let info = "";
  try {
    execFileSync(ffmpeg, ["-hide_banner", "-i", file], { stdio: "pipe" });
  } catch (e) {
    info = String((e as { stderr?: Buffer }).stderr ?? "");
  }
  const m = /Duration: (\d+):(\d+):([\d.]+)/.exec(info);
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : NaN;
}

for (const file of readdirSync(videoDir).filter((f) => f.endsWith(".webm"))) {
  const out = path.join(mp4Dir, file.replace(/\.webm$/, ".mp4"));
  run(["-ss", String(LEAD), "-i", path.join(videoDir, file), ...H264, "-movflags", "+faststart", out]);
  console.log(`ok ${out}`);
}

// Escena 3 del guion = handoff en portugués + inyección bloqueada, en una sola toma de ≤ 40 s: se quita la tarjeta
// de título de la segunda parte y, si aun así pasa del tope, se acelera apenas lo necesario.
const partA = path.join(mp4Dir, "escena3a_fraude_pt.mp4");
const partB = path.join(mp4Dir, "escena3b_inyeccion.mp4");
const skipB = 1.5;
const total = duration(partA) + duration(partB) - skipB;
const speed = Math.max(1, total / (SCENE3_MAX - 0.5));
run([
  ...["-i", partA, "-ss", String(skipB), "-i", partB],
  "-filter_complex",
  `[0:v][1:v]concat=n=2:v=1:a=0,setpts=PTS/${speed.toFixed(4)}[v]`,
  ...["-map", "[v]", ...H264, "-movflags", "+faststart", path.join(mp4Dir, "escena3_pt_e_inyeccion.mp4")],
]);
console.log(`escena 3 unida: ${total.toFixed(1)} s → velocidad ×${speed.toFixed(2)}`);

for (const file of readdirSync(mp4Dir).filter((f) => f.endsWith(".mp4"))) {
  console.log(`${file}\t${duration(path.join(mp4Dir, file)).toFixed(1)} s`);
}
