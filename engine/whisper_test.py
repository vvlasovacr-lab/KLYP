from faster_whisper import WhisperModel

model = WhisperModel(
    "medium",
    device="cpu",
    compute_type="int8"
)

segments, info = model.transcribe(
    "input/video.mp4",
    language="ru",
    word_timestamps=True
)

print("Язык:", info.language)

with open("output/transcript.txt", "w", encoding="utf-8") as f:
    for segment in segments:
        text = segment.text.strip()

        print(
            f"{segment.start:.2f} --> {segment.end:.2f}: {text}"
        )

        f.write(
            f"{segment.start:.2f} --> {segment.end:.2f}: {text}\n"
        )

print("Готово!")