import os

exe_path = r"C:\Users\divik\OneDrive\Desktop\Homework\divAI\node_modules\@anthropic-ai\claude-code\bin\claude.exe"

print("Reading 250MB binary into memory...")
with open(exe_path, "rb") as f:
    binary_data = f.read()

print("Patching Anthropic terracotta (#da7756) to neon blue (#00aaff)...")
patched_data = binary_data.replace(b"#da7756", b"#00aaff")

with open(exe_path, "wb") as f:
    f.write(patched_data)

print("Binary color patched successfully.")
