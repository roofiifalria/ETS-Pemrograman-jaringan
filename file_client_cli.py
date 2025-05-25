import socket
import json
import base64
import logging
import os 

server_address=('0.0.0.0',7777) # Pastikan ini sesuai dengan IP dan port server Anda

def send_command(command_str=""):
    """
    Mengirim perintah ke server dan menerima respons.
    """
    global server_address
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(server_address)
        logging.warning(f"Connecting to {server_address}")
    except ConnectionRefusedError:
        logging.error(f"Connection refused. Ensure the server is running on {server_address}")
        return False
    except Exception as e:
        logging.error(f"Error connecting to server: {e}")
        return False

    try:
        # Tambahkan pemisah \r\n\r\n di akhir setiap perintah yang dikirim
        full_command = command_str + "\r\n\r\n" 
        logging.warning(f"Sending message: {full_command[:100]}...") # Log hanya sebagian kecil jika terlalu panjang
        sock.sendall(full_command.encode())
        
        data_received="" #empty string
        while True:
            # Tingkatkan ukuran buffer untuk potensi respons yang lebih besar
            data = sock.recv(4096) 
            if data:
                data_received += data.decode()
                # Server juga mengirim JSON diikuti oleh \r\n\r\n
                if "\r\n\r\n" in data_received:
                    break
            else:
                # Tidak ada data lagi, server menutup koneksi atau sudah mengirim semua
                break
        
        # Pisahkan data untuk mengisolasi bagian JSON
        json_part = data_received.split("\r\n\r\n")[0]
        hasil = json.loads(json_part)
        logging.warning("Data received from server:")
        return hasil
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from server: {e}. Received data: '{data_received}'")
        return False
    except Exception as e:
        logging.error(f"Error during data receiving: {e}")
        return False
    finally:
        sock.close() # Pastikan socket ditutup

def remote_list():
    """
    Mengirim perintah LIST ke server dan menampilkan daftar file.
    """
    command_str=f"LIST"
    hasil = send_command(command_str)
    # Periksa hasil adalah dict dan statusnya OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        print("Daftar file:")
        if 'data' in hasil and isinstance(hasil['data'], list):
            for nmfile in hasil['data']:
                print(f"- {nmfile}")
        else:
            print("Tidak ada file atau format data tidak valid dari server.")
        return True
    else:
        print("Gagal mengambil daftar file.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Pesan server: {hasil['data']}")
        return False

def remote_get(filename=""):
    """
    Mengambil file dari server dan menyimpannya secara lokal.
    """
    command_str=f"GET {filename}"
    hasil = send_command(command_str)
    # Periksa hasil adalah dict dan statusnya OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        namafile = hasil.get('data_namafile')
        isifile_b64 = hasil.get('data_file')

        if not namafile or not isifile_b64:
            print("Respons server tidak lengkap (nama file atau konten file Base64 hilang).")
            return False

        try:
            isifile = base64.b64decode(isifile_b64)
        except base64.binascii.Error as e:
            print(f"Gagal mendekode konten file Base64: {e}. Pastikan file bukan korup.")
            return False

        try:
            with open(namafile,'wb+') as fp:
                fp.write(isifile)
            print(f"File '{namafile}' berhasil diunduh.")
            return True
        except Exception as e:
            print(f"Gagal menulis file '{namafile}': {e}")
            return False
    else:
        print(f"Gagal mengunduh file '{filename}'.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Pesan server: {hasil['data']}")
        return False

def remote_upload(filename=""):
    """
    Mengunggah file dari lokal ke server setelah di-encode Base64.
    """
    if not os.path.exists(filename):
        print(f"Error: File lokal '{filename}' tidak ditemukan.")
        return False

    try:
        with open(filename, 'rb') as fp:
            file_content = fp.read()
            encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        # Kirim perintah UPLOAD dengan nama file dan konten Base64
        command_str = f"UPLOAD {filename} {encoded_content}"
        hasil = send_command(command_str)

        # Periksa hasil adalah dict dan statusnya OK
        if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
            print(f"File '{filename}' berhasil diupload.")
            return True
        else:
            print(f"Gagal mengupload file '{filename}'.")
            if hasil and isinstance(hasil, dict) and 'data' in hasil:
                print(f"Pesan server: {hasil['data']}")
            return False
    except Exception as e:
        print(f"Error saat mengupload file '{filename}': {e}")
        return False

def remote_delete(filename=""):
    """
    Menghapus file di server.
    """
    command_str = f"DELETE {filename}"
    hasil = send_command(command_str)

    # Periksa hasil adalah dict dan statusnya OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        print(f"File '{filename}' berhasil dihapus dari server.")
        return True
    else:
        print(f"Gagal menghapus file '{filename}' dari server.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Pesan server: {hasil['data']}")
        return False

if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING) # Atur level logging untuk visibilitas
    # Pastikan ini adalah alamat IP dan port server yang benar
    server_address=('172.16.16.101',6667) 

    print("--- Listing files ---")
    remote_list()

    # Membuat file dummy untuk diupload
    dummy_upload_filename = "upload_test.txt"
    try:
        with open(dummy_upload_filename, 'w') as f:
            f.write("Ini adalah file yang diupload dari klien.")
        
        print(f"\n--- Uploading '{dummy_upload_filename}' ---")
        remote_upload(dummy_upload_filename)

        print("\n--- Listing files after upload ---")
        remote_list()

        # Mengambil file yang baru saja diupload
        print(f"\n--- Getting '{dummy_upload_filename}' ---")
        remote_get(dummy_upload_filename)

        # Menghapus file yang baru saja diupload
        print(f"\n--- Deleting '{dummy_upload_filename}' ---")
        remote_delete(dummy_upload_filename)

        print("\n--- Listing files after delete ---")
        remote_list()

    finally: # Pastikan file dummy lokal dihapus, terlepas dari hasil operasi
        # Bersihkan file dummy lokal yang dibuat untuk upload
        if os.path.exists(dummy_upload_filename):
            os.remove(dummy_upload_filename)
        # Bersihkan file dummy lokal yang mungkin dibuat saat 'get' (jika namanya sama)
        if os.path.exists(dummy_upload_filename): 
            os.remove(dummy_upload_filename)

    # Contoh tambahan: coba ambil file yang mungkin sudah ada di server
    # print("\n--- Getting 'donalbebek.jpg' (if exists on server) ---")
    # remote_get('donalbebek.jpg')