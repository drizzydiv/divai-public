import os

exe_path = r"C:\Users\divik\OneDrive\Desktop\Homework\divAI\node_modules\@anthropic-ai\claude-code\bin\claude.exe"

print("Reading 250MB binary into memory...")
with open(exe_path, "rb") as f:
    binary_data = f.read()

print("Patching V8 memory snapshot strings...")
# Pad "divAI" with 6 spaces so we don't shift the executable offsets and corrupt the file
patched_data = binary_data.replace(b"Claude Code", b"divAI      ")

with open(exe_path, "wb") as f:
    f.write(patched_data)

print("Binary hex-edited successfully.")
