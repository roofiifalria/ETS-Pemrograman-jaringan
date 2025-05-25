import socket
import json
import base64
import os
import time
import random
import threading
import multiprocessing
import concurrent.futures
import csv
import sys
import logging

# --- Konfigurasi Awal ---
# Konfigurasi logging untuk client
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] (%(name)-10s) %(message)s')
logger = logging.getLogger('ClientStressTest')
logger.setLevel(logging.INFO) # Ganti ke logging.DEBUG untuk detail log lebih banyak

# Direktori untuk file dummy dan downloaded files
DUMMY_FILES_DIR = 'dummy_files'
DOWNLOADED_FILES_DIR = 'downloaded_files'
SERVER_FILES_DIR = 'server_files' # Pastikan ini konsisten dengan server

# Ukuran buffer untuk menerima data dari socket
SOCKET_BUFFER_SIZE = 65536
SOCKET_TIMEOUT = 120 # detik, sesuaikan dengan timeout server

# --- Fungsi Utility File ---
def ensure_directories_exist():
    """Memastikan direktori yang diperlukan ada."""
    os.makedirs(DUMMY_FILES_DIR, exist_ok=True)
    os.makedirs(DOWNLOADED_FILES_DIR, exist_ok=True)
    # Direktori server_files seharusnya diurus oleh server, tapi bisa juga dicek di sini jika perlu
    # os.makedirs(SERVER_FILES_DIR, exist_ok=True) 

def generate_dummy_file(filename, size_mb):
    """Menghasilkan file dummy dengan ukuran tertentu dalam MB."""
    filepath = os.path.join(DUMMY_FILES_DIR, filename)
    size_bytes = size_mb * 1024 * 1024
    
    if os.path.exists(filepath) and os.path.getsize(filepath) == size_bytes:
        logger.debug(f"Dummy file {filename} ({size_mb}MB) already exists, skipping generation.")
        return filepath
    
    logger.info(f"Generating dummy file: {filename} ({size_mb}MB)...")
    try:
        with open(filepath, 'wb') as f:
            # Menulis byte acak untuk mengisi file
            f.write(os.urandom(size_bytes)) 
        logger.info(f"Dummy file {filename} generated successfully.")
        return filepath
    except Exception as e:
        logger.error(f"Error generating dummy file {filename}: {e}", exc_info=True)
        raise

# --- Fungsi Komunikasi Client-Server ---
def create_client_socket(server_address):
    """Membuat dan menghubungkan socket ke server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(server_address)
        sock.settimeout(SOCKET_TIMEOUT) # Atur timeout di sisi client juga
        return sock
    except Exception as e:
        logger.error(f"Failed to connect to server {server_address}: {e}")
        return None

def receive_full_response(sock):
    """Menerima seluruh respon dari server hingga ditemukan delimiter."""
    full_response_buffer = b""
    start_time = time.time()
    while True:
        try:
            data = sock.recv(SOCKET_BUFFER_SIZE)
            if not data:
                # Koneksi ditutup oleh server
                logger.debug("Server closed connection during response receive.")
                break 
            full_response_buffer += data
            if b"\r\n\r\n" in full_response_buffer:
                break
            
            if time.time() - start_time > SOCKET_TIMEOUT:
                logger.warning(f"Response receive timeout reached ({SOCKET_TIMEOUT}s). Partial data: {len(full_response_buffer)} bytes.")
                break
        except socket.timeout:
            logger.warning(f"Socket timeout during response receive after {time.time() - start_time:.2f}s.")
            break
        except Exception as e:
            logger.error(f"Error receiving response: {e}", exc_info=True)
            break
            
    return full_response_buffer

def send_and_receive_command(sock, command_str, file_content_b64=None):
    """Mengirim perintah dan menerima respon dari server."""
    try:
        request_data = command_str.encode('utf-8') + b"\r\n\r\n"
        if file_content_b64:
            request_data += file_content_b64.encode('utf-8')
        
        sock.sendall(request_data)

        # Menerima response
        full_response_buffer = receive_full_response(sock)
        
        response_parts = full_response_buffer.split(b"\r\n\r\n", 1)
        if len(response_parts) < 1:
            logger.error("Invalid response format: Missing separator.")
            return {"status": "ERROR", "data": "Invalid server response format."}
            
        response_header = response_parts[0].decode('utf-8')
        response_body = response_parts[1] if len(response_parts) > 1 else b""

        try:
            response_dict = json.loads(response_header)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON response header: '{response_header[:200]}...'")
            return {"status": "ERROR", "data": "Invalid JSON response from server."}

        # Untuk GET command, konten file ada di body
        if response_dict.get('status') == 'OK' and command_str.startswith('GET'):
            response_dict['data'] = response_body.decode('utf-8') # Dekode konten base64
            
        return response_dict
    except socket.timeout:
        logger.error("Socket timeout during send or receive operation.")
        return {"status": "ERROR", "data": "Socket operation timed out."}
    except Exception as e:
        logger.error(f"Error during socket communication: {e}", exc_info=True)
        return {"status": "ERROR", "data": f"Network error: {str(e)}"}
    finally:
        # Socket ditutup di client_task
        pass

# --- Fungsi Task Client ---
def client_task(task_id, server_address, operation, file_size_mb):
    """
    Representasi sebuah worker client yang melakukan operasi.
    Mengembalikan dictionary hasil untuk agregasi.
    """
    start_time_task = time.time()
    success = False
    bytes_processed = 0
    filename_prefix = f"test_file_{file_size_mb}MB" # Nama file tanpa ID task untuk upload/download
    filename = f"{filename_prefix}_{task_id}.bin" # Nama file dengan ID task (jika unik diperlukan)

    sock = None
    try:
        sock = create_client_socket(server_address)
        if not sock:
            raise ConnectionError(f"Failed to connect for task {task_id}.")

        if operation == 'UPLOAD':
            # Untuk upload, kita perlu nama file yang sama untuk semua client pada volume yang sama
            # agar file dummy tidak dibuat berkali-kali jika tidak diperlukan.
            # Namun, untuk menghindari konflik penulisan/pembacaan di server, 
            # kita tetap upload dengan nama unik per task_id.
            # Jadi, buat file dummy dengan nama generik dulu, lalu upload dengan nama spesifik.
            dummy_file_path = generate_dummy_file(f"{filename_prefix}.bin", file_size_mb)
            if not dummy_file_path:
                raise FileNotFoundError(f"Failed to generate dummy file {filename_prefix}.bin")

            with open(dummy_file_path, 'rb') as f:
                content = f.read()
            encoded_content = base64.b64encode(content).decode('utf-8')
            
            logger.debug(f"Client {task_id} UPLOADING {filename} ({file_size_mb}MB) to {server_address}...")
            response = send_and_receive_command(sock, f"UPLOAD {filename}", encoded_content)
            
            if response.get('status') == 'OK':
                success = True
                bytes_processed = len(content)
                logger.info(f"Client {task_id} UPLOAD {filename} successful.")
            else:
                logger.error(f"Client {task_id} UPLOAD {filename} failed: {response.get('data')}")

        elif operation == 'DOWNLOAD':
            # Untuk download, kita mencoba download file yang *seharusnya* sudah diupload oleh salah satu client
            # atau sudah ada di server (misalnya dari upload sebelumnya).
            # Menggunakan nama file yang sama seperti saat diupload.
            filename_to_download = f"{filename_prefix}_{task_id}.bin" # Download file yang diupload oleh client ini
            
            logger.debug(f"Client {task_id} DOWNLOADING {filename_to_download} ({file_size_mb}MB) from {server_address}...")
            response = send_and_receive_command(sock, f"GET {filename_to_download}")
            
            if response.get('status') == 'OK' and response.get('data') is not None:
                downloaded_filepath = os.path.join(DOWNLOADED_FILES_DIR, filename_to_download)
                try:
                    decoded_content = base64.b64decode(response['data'])
                    with open(downloaded_filepath, 'wb') as f:
                        f.write(decoded_content)
                    success = True
                    bytes_processed = len(decoded_content)
                    logger.info(f"Client {task_id} DOWNLOAD {filename_to_download} successful, size: {bytes_processed} bytes.")
                except Exception as e:
                    logger.error(f"Client {task_id} DOWNLOAD {filename_to_download} failed (decode/write): {e}", exc_info=True)
            else:
                logger.error(f"Client {task_id} DOWNLOAD {filename_to_download} failed: {response.get('data')}")
        
        elif operation == 'LIST':
            logger.debug(f"Client {task_id} LISTING files from {server_address}...")
            response = send_and_receive_command(sock, "LIST")
            if response.get('status') == 'OK':
                success = True
                # Bytes processed for LIST is negligible, can be 0 or small constant
                bytes_processed = len(json.dumps(response.get('data')).encode('utf-8'))
                logger.info(f"Client {task_id} LIST successful. Found {len(response.get('data', []))} files.")
            else:
                logger.error(f"Client {task_id} LIST failed: {response.get('data')}")
        
        # NOTE: DELETE operation is not included in the stress test combinations
        # to avoid deleting files that other clients might need for DOWNLOAD.
        # If DELETE is needed, ensure careful management of file lifecycle.

    except ConnectionError as ce:
        logger.error(f"Client {task_id} connection error: {ce}")
    except Exception as e:
        logger.error(f"Client {task_id} unhandled error: {e}", exc_info=True)
    finally:
        if sock:
            sock.close()
    
    end_time_task = time.time()
    duration = end_time_task - start_time_task
    # Hindari ZeroDivisionError jika duration sangat kecil atau 0
    throughput = bytes_processed / duration if duration > 0 else 0 

    return {
        'task_id': task_id,
        'success': success,
        'duration': duration,
        'bytes_processed': bytes_processed,
        'throughput': throughput
    }

# --- Fungsi Eksekusi Stress Test ---
def run_stress_test_scenario(server_ip, server_port, client_pool_type, num_client_workers, 
                             operation, file_size_mb, num_server_workers_target):
    """
    Menjalankan satu skenario stress test dan mengumpulkan hasilnya.
    """
    server_address = (server_ip, server_port)
    results = []

    logger.info(f"\n--- Starting Scenario ---")
    logger.info(f"  Server: {server_ip}:{server_port}")
    logger.info(f"  Client Pool Type: {client_pool_type.upper()}")
    logger.info(f"  Client Workers: {num_client_workers}")
    logger.info(f"  Operation: {operation}")
    logger.info(f"  File Size: {file_size_mb}MB")
    logger.info(f"  Server Workers (Target for Report): {num_server_workers_target}")


    ExecutorClass = concurrent.futures.ThreadPoolExecutor
    if client_pool_type == 'process':
        ExecutorClass = concurrent.futures.ProcessPoolExecutor

    start_total_time = time.time()
    try:
        with ExecutorClass(max_workers=num_client_workers) as executor:
            futures = [executor.submit(client_task, i + 1, server_address, operation, file_size_mb) 
                       for i in range(num_client_workers)]
            
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
    except Exception as e:
        logger.critical(f"Error initializing or running client pool for scenario: {e}", exc_info=True)
        # Populate results with failures if the pool itself failed
        for i in range(num_client_workers):
            results.append({
                'task_id': i + 1, 'success': False, 'duration': 0, 
                'bytes_processed': 0, 'throughput': 0
            })

    end_total_time = time.time()

    successful_clients = sum(1 for r in results if r and r['success'])
    failed_clients = num_client_workers - successful_clients
    
    total_duration_all_clients = sum(r['duration'] for r in results if r and r['success'])
    avg_duration_per_client = total_duration_all_clients / successful_clients if successful_clients > 0 else 0
    
    total_bytes_processed_all_clients = sum(r['bytes_processed'] for r in results if r and r['success'])
    avg_throughput_per_client = total_bytes_processed_all_clients / total_duration_all_clients if total_duration_all_clients > 0 else 0

    # Estimasi worker server yang sukses/gagal didasarkan pada client yang sukses/gagal
    # Ini adalah asumsi karena client tidak memiliki akses langsung ke metrik server.
    server_workers_successful = successful_clients 
    server_workers_failed = failed_clients

    logger.info(f"--- Scenario Finished ---")
    logger.info(f"  Successful Client Tasks: {successful_clients}/{num_client_workers}")
    logger.info(f"  Avg Client Duration: {avg_duration_per_client:.4f}s")
    logger.info(f"  Avg Client Throughput: {avg_throughput_per_client:.2f} Bytes/s")
    
    return {
        'total_clients_run': num_client_workers,
        'successful_clients': successful_clients,
        'failed_clients': failed_clients,
        'avg_duration_per_client': avg_duration_per_client,
        'avg_throughput_per_client': avg_throughput_per_client,
        'server_workers_successful': server_workers_successful,
        'server_workers_failed': server_workers_failed
    }

# --- Main Program ---
def main():
    ensure_directories_exist()

    if len(sys.argv) != 4:
        print("Usage: python file_client_stress_test.py <server_ip> <server_port> <client_worker_type>")
        print("  <client_worker_type>: 'thread' or 'process'")
        sys.exit(1)

    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    client_pool_type = sys.argv[3].lower() # 'thread' or 'process'

    if client_pool_type not in ['thread', 'process']:
        logger.error("Invalid <client_worker_type>. Must be 'thread' or 'process'.")
        sys.exit(1)

    # --- Definisi Skenario ---
    operations = ['UPLOAD', 'DOWNLOAD']
    volume_sizes_mb = [10, 50, 100]
    num_client_worker_pools = [1, 5, 50]
    num_server_worker_pools_target = [1, 5, 50] # Ini adalah target, server harus dijalankan secara manual

    # Persiapan CSV output
    output_filename = f"stress_test_results_client_{client_pool_type}.csv"
    fieldnames = [
        'Nomor', 'Operasi', 'Volume (MB)', 'Jumlah Client Worker Pool', 
        'Jumlah Server Worker Pool (Target)', 'Waktu Total Per Client (s)', 
        'Throughput Per Client (Bytes/s)', 'Client Sukses', 'Client Gagal',
        'Server Sukses (Est.)', 'Server Gagal (Est.)'
    ]

    print(f"\n--- Preparing to run stress tests ---")
    print(f"Results will be saved to: {output_filename}")
    print(f"Make sure your server is running with the correct number of workers for each scenario.")
    print(f"Example server commands:")
    print(f"  For Thread Server: python file_server_thread_pool.py <num_workers> {server_port}")
    print(f"  For Process Server: python file_server_process_pool.py <num_workers> {server_port}")
    print(f"\nSTARTING TEST IN 5 SECONDS. Press Ctrl+C to abort.")
    time.sleep(5)

    with open(output_filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        scenario_counter = 0
        total_scenarios = len(operations) * len(volume_sizes_mb) * \
                          len(num_client_worker_pools) * len(num_server_worker_pools_target)

        for operation in operations:
            for volume_mb in volume_sizes_mb:
                for num_client_workers in num_client_worker_pools:
                    for num_server_workers_target in num_server_worker_pools_target:
                        scenario_counter += 1
                        logger.info(f"\n[{scenario_counter}/{total_scenarios}] Running scenario: "
                                    f"Op={operation}, Vol={volume_mb}MB, "
                                    f"ClientPool={client_pool_type.upper()}, C-Workers={num_client_workers}, "
                                    f"S-Workers(Target)={num_server_workers_target}")
                        print(f"!!! IMPORTANT: Ensure server is running with {num_server_workers_target} workers !!!")

                        try:
                            scenario_results = run_stress_test_scenario(
                                server_ip, server_port, 
                                client_pool_type, 
                                num_client_workers, 
                                operation, 
                                volume_mb,
                                num_server_workers_target
                            )

                            writer.writerow({
                                'Nomor': scenario_counter,
                                'Operasi': operation,
                                'Volume (MB)': volume_mb,
                                'Jumlah Client Worker Pool': num_client_workers,
                                'Jumlah Server Worker Pool (Target)': num_server_workers_target,
                                'Waktu Total Per Client (s)': f"{scenario_results['avg_duration_per_client']:.4f}",
                                'Throughput Per Client (Bytes/s)': f"{scenario_results['avg_throughput_per_client']:.2f}",
                                'Client Sukses': scenario_results['successful_clients'],
                                'Client Gagal': scenario_results['failed_clients'],
                                'Server Sukses (Est.)': scenario_results['server_workers_successful'],
                                'Server Gagal (Est.)': scenario_results['server_workers_failed']
                            })
                            csvfile.flush() # Pastikan data ditulis segera ke file
                        except KeyboardInterrupt:
                            logger.info("Stress test aborted by user.")
                            sys.exit(0)
                        except Exception as e:
                            logger.error(f"Unhandled error during scenario {scenario_counter}: {e}", exc_info=True)
                            writer.writerow({
                                'Nomor': scenario_counter,
                                'Operasi': operation,
                                'Volume (MB)': volume_mb,
                                'Jumlah Client Worker Pool': num_client_workers,
                                'Jumlah Server Worker Pool (Target)': num_server_workers_target,
                                'Waktu Total Per Client (s)': 'ERROR',
                                'Throughput Per Client (Bytes/s)': 'ERROR',
                                'Client Sukses': 'ERROR',
                                'Client Gagal': 'ERROR',
                                'Server Sukses (Est.)': 'ERROR',
                                'Server Gagal (Est.)': 'ERROR'
                            })
                            csvfile.flush()
    logger.info(f"\nAll stress test scenarios completed. Results saved to {output_filename}")

if __name__ == "__main__":
    multiprocessing.freeze_support() # Penting untuk multiprocessing di Windows
    main()