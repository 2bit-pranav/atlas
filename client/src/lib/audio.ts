/**
 * Voice input, as llama.cpp's web UI does it: record, and send the recording
 * itself as an audio attachment. No speech-to-text step -- Gemma hears the
 * audio through its own multimodal projector, so nothing else is installed.
 *
 * Browsers record compressed audio (webm/opus). llama-server accepts wav or
 * mp3, so the recording is decoded and re-encoded as 16 kHz mono 16-bit WAV,
 * which is what speech models expect and keeps the file small.
 */

const RATE = 16000

export class Recorder {
  private recorder: MediaRecorder | null = null
  private chunks: Blob[] = []
  private stream: MediaStream | null = null
  startedAt = 0

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this.chunks = []
    this.recorder = new MediaRecorder(this.stream)
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data)
    this.recorder.start()
    this.startedAt = Date.now()
  }

  /** Stop and return the recording as a WAV file, or null if it was cancelled. */
  async stop(keep = true): Promise<File | null> {
    const recorder = this.recorder
    if (!recorder) return null
    const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()))
    recorder.stop()
    await done
    this.stream?.getTracks().forEach((t) => t.stop())
    this.recorder = null
    this.stream = null
    if (!keep || !this.chunks.length) return null
    const wav = await toWav(new Blob(this.chunks, { type: recorder.mimeType }))
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")
    return new File([wav], `recording-${stamp}.wav`, { type: "audio/wav" })
  }
}

async function toWav(blob: Blob): Promise<Blob> {
  const decoded = await new AudioContext().decodeAudioData(await blob.arrayBuffer())
  const frames = Math.ceil(decoded.duration * RATE)
  const offline = new OfflineAudioContext(1, frames, RATE)
  const source = offline.createBufferSource()
  source.buffer = decoded
  source.connect(offline.destination)
  source.start()
  const samples = (await offline.startRendering()).getChannelData(0)

  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  text(0, "RIFF")
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, "WAVE")
  text(12, "fmt ")
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)        // PCM
  view.setUint16(22, 1, true)        // mono
  view.setUint32(24, RATE, true)
  view.setUint32(28, RATE * 2, true) // byte rate
  view.setUint16(32, 2, true)        // block align
  view.setUint16(34, 16, true)       // bits per sample
  text(36, "data")
  view.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buffer], { type: "audio/wav" })
}
