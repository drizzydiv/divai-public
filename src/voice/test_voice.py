"""
Run this before wiring Azure TTS into the main loop.
Verifies pause timing, flow, and voice quality.

Usage:
    cd src/voice
    python test_voice.py
"""
from tts import speak, speak_stream

print("Test 1 — comma and period pause timing...")
speak("Contradiction flagged. Two sources confirm the post, one doesn't.")

print("Test 2 — multiple sentences, no hesitation between them...")
speak("Three sources confirm the timeline. One doesn't. That's where we start.")

print("Test 3 — technical terms and proper nouns...")
speak(
    "Wayback Machine returned fourteen archived versions. "
    "Earliest capture is March 2006, two weeks before Shaffer disappeared."
)

print("Test 4 — divAI daily use voice...")
speak(
    "You have an assignment due in 48 hours. "
    "Last commit on that repo was four days ago."
)

print("Test 5 — single cinematic sentence...")
speak("That's everything the public record has. Here's where it runs out.")

print("Test 6 — long brief via speak_stream (should start immediately)...")
brief = (
    "Brian Shaffer case brief generated. Timeline verified across eleven sources. "
    "Three contradictions flagged for manual review. Priority lead is the "
    "condolence book post dated September 2008, two years post-disappearance. "
    "Source attribution unverified. Recommend Wayback Machine query on the "
    "obituary URL as first step. Cell tower ping in Hilliard cross-referenced "
    "against public tower data. Location is consistent with reported sighting "
    "in the Michigan corridor. No further corroboration found in public record."
)
speak_stream(brief)

print("All tests complete.")
