import socket
import threading
import logging
import json
import concurrent.futures
import sys
import os
import time
import base64

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] (%(threadName)-10s) %(message)s')
# logging.getLogger().setLevel(logging.DEBUG) # Uncomment for detailed server debugging

from file_interface import FileInterface

def process_client_request(connection, address):
    """
    Fungsi ini akan dijalankan oleh setiap thread di ThreadPoolExecutor.
    """
    fp = FileInterface()

    full_data_buffer = b"" 
    header_str = ""
    
    try:
        connection.settimeout(120) # Set timeout untuk menghindari blocking selamanya

        # Langkah 1: Menerima Header dan sisa data setelah header
        while True:
            data = connection.recv(65536) # Menerima data
            if not data:
                logging.info(f"Client {address} disconnected during receive or no data. Closing connection.")
                return 

            full_data_buffer += data
            separator_index = full_data_buffer.find(b"\r\n\r\n")

            if separator_index != -1:
                header_str = full_data_buffer[:separator_index].decode('utf-8')
                file_body_bytes = full_data_buffer[separator_index + 4:] # Sisa data adalah body
                break
        
        if not header_str:
            logging.info(f"No command header received from {address}. Closing connection.")
            return

        command_and_params = header_str
        parts = command_and_params.split(' ', 2)
        command = parts[0].upper()
        params = parts[1:] if len(parts) > 1 else []

        hasil_dict = {}

        if command == 'UPLOAD':
            if len(params) < 1: 
                hasil_dict = dict(status='ERROR', data='Filename missing for UPLOAD.')
            else:
                filename_to_upload = params[0]
                try:
                    file_content_b64 = file_body_bytes.decode('utf-8')
                    hasil_dict = fp.upload(filename_to_upload, file_content_b64) 

                    if hasil_dict.get('status') == 'OK':
                        try:
                            total_uploaded_bytes = len(base64.b64decode(file_content_b64))
                            logging.info(f"UPLOAD of {filename_to_upload} from {address} completed. Original size: {total_uploaded_bytes} bytes.")
                        except Exception as e:
                            logging.warning(f"Could not decode Base64 to get original size for logging: {e}")
                    else:
                        logging.error(f"FileInterface.upload failed for {filename_to_upload}: {hasil_dict.get('data')}")
                except UnicodeDecodeError:
                    logging.error(f"Failed to decode UPLOAD body as UTF-8 for {address} for {filename_to_upload}. This might indicate corrupted Base64 data.", exc_info=True)
                    hasil_dict = dict(status='ERROR', data="Failed to decode file content.")
                except Exception as e:
                    logging.error(f"Error processing UPLOAD for {filename_to_upload} from {address}: {e}", exc_info=True)
                    hasil_dict = dict(status='ERROR', data=f"Server internal error during UPLOAD: {str(e)}")

        elif command == 'LIST':
            hasil_dict = fp.list(params)
        elif command == 'GET':
            hasil_dict = fp.get(params)
        elif command == 'DELETE':
            hasil_dict = fp.delete(params)
        else:
            hasil_dict = dict(status='ERROR', data=f'Unknown command: {command}')

    except socket.timeout:
        logging.error(f"Socket timeout for {address} during receive. Closing connection.", exc_info=True)
        hasil_dict = dict(status='ERROR', data="Server receive timeout.")
    except Exception as e:
        logging.error(f"Error processing client {address} command: {e}", exc_info=True)
        hasil_dict = dict(status='ERROR', data=f'Server internal error: {str(e)}')
    finally:
        response_str = json.dumps(hasil_dict) + "\r\n\r\n"
        try:
            connection.sendall(response_str.encode('utf-8'))
        except Exception as e:
            logging.error(f"Error sending response to {address}: {e}", exc_info=True)
        finally:
            connection.close()

class ServerThreadPool(threading.Thread):
    def __init__(self, ipaddress='0.0.0.0', port=8889, num_workers=5):
        self.ipinfo = (ipaddress, port)
        self.my_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.my_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=num_workers)
        self._shutdown_event = threading.Event()
        super().__init__()

    def run(self):
        logging.info(f"Server (ThreadPool) running on {self.ipinfo} with {self.executor._max_workers} workers")
        try:
            self.my_socket.bind(self.ipinfo)
            self.my_socket.listen(50)
            self.my_socket.settimeout(1.0) # Set timeout untuk accept()

            while not self._shutdown_event.is_set():
                try:
                    connection, client_address = self.my_socket.accept()
                    logging.info(f"Connection from {client_address}")
                    if not self._shutdown_event.is_set():
                        self.executor.submit(process_client_request, connection, client_address)
                    else:
                        logging.info("Server is shutting down, refusing new connection.")
                        connection.close()
                except socket.timeout:
                    pass
                except Exception as e:
                    if not self._shutdown_event.is_set():
                        logging.error(f"Error accepting connection: {e}", exc_info=True)
                    else:
                        logging.info(f"Server stopping accept loop due to shutdown event: {e}")
                    break

        except Exception as e:
            logging.critical(f"Server error: {e}", exc_info=True)
        finally:
            logging.info("Shutting down server resources...")
            self.my_socket.close()
            self.executor.shutdown(wait=True)
            logging.info("Server shutdown complete.")

    def shutdown(self):
        logging.info("Initiating server shutdown...")
        self._shutdown_event.set()
        try:
            self.my_socket.shutdown(socket.SHUT_RDWR)
        except OSError as e:
            logging.warning(f"Error shutting down socket (might be already closed): {e}")
        self.my_socket.close()
        self.join()

def main():
    if len(sys.argv) < 2:
        print("Usage: python file_server_thread_pool.py <num_workers_server> [port]")
        sys.exit(1)
    
    num_workers_server = int(sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6667

    server = ServerThreadPool(ipaddress='0.0.0.0', port=port, num_workers=num_workers_server)
    server.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received in main. Signalling server to shutdown.")
        server.shutdown()

if __name__ == "__main__":
    main()