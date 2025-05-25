# make_dummy_files.py
import os

def create_dummy_file(filename, size_mb):
    size_bytes = size_mb * 1024 * 1024
    print(f"Creating {filename} of size {size_mb} MB ({size_bytes} bytes)...")
    try:
        with open(filename, 'wb') as f:
            # Menulis byte acak lebih baik untuk simulasi data asli
            f.write(os.urandom(size_bytes))
        print(f"Successfully created {filename}")
    except Exception as e:
        print(f"Error creating {filename}: {e}")

if __name__ == "__main__":
    current_dir = os.getcwd()
    print(f"Creating dummy files in: {current_dir}")
    create_dummy_file('10MB.bin', 10)
    create_dummy_file('50MB.bin', 50)
    create_dummy_file('100MB.bin', 100)
    print("Dummy file creation complete.")