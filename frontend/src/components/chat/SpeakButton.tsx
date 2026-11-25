import { Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import { IconButton } from "../ui/Button";

/** Quita la sintaxis Markdown para que la voz no lea asteriscos ni bloques de código. */
export function toSpeech(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " (bloque de código omitido) ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_~>|]+/g, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

function spanishVoice(): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang.startsWith("es") && v.localService) ?? voices.find((v) => v.lang.startsWith("es"));
}

/**
 * Lee la respuesta en voz alta con las voces del sistema operativo (locales en Windows:
 * no se envía el texto a ningún servidor).
 */
export function SpeakButton({ text }: { text: string }) {
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    return () => {
      if (speaking) window.speechSynthesis.cancel();
    };
  }, [speaking]);

  if (!supported) return null;

  const toggle = () => {
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(toSpeech(text));
    utterance.lang = "es-ES";
    const voice = spanishVoice();
    if (voice) utterance.voice = voice;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  };

  return (
    <IconButton label={speaking ? "Detener lectura" : "Leer en voz alta"} className="size-7" onClick={toggle}>
      {speaking ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}
    </IconButton>
  );
}
