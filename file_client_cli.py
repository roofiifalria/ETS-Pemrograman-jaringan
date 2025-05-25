import socket
import json
import base64
import logging
import os 

# Configure logging for the client
logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] (%(name)-10s) %(message)s')
logger = logging.getLogger('SimpleClient')
logger.setLevel(logging.INFO) # Change to logging.DEBUG for more detailed logs

# Ensure this matches your server's IP and port
server_address=('0.0.0.0',7777) 

def send_command(command_str=""):
    """
    Sends a command to the server and receives the response.
    """
    global server_address
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(server_address)
        logger.warning(f"Connecting to {server_address}")
    except ConnectionRefusedError:
        logging.error(f"Connection refused. Ensure the server is running on {server_address}")
        return False
    except Exception as e:
        logging.error(f"Error connecting to server: {e}")
        return False

    try:
        # Add the \r\n\r\n delimiter at the end of each command sent
        full_command = command_str + "\r\n\r\n" 
        logger.warning(f"Sending message: {full_command[:100]}...") # Log only a small part if it's too long
        sock.sendall(full_command.encode())
        
        data_received="" # Empty string
        while True:
            # Increase buffer size for potentially larger responses
            data = sock.recv(4096) 
            if data:
                data_received += data.decode()
                # The server also sends JSON followed by \r\n\r\n
                if "\r\n\r\n" in data_received:
                    break
            else:
                # No more data, server closed connection or already sent everything
                break
        
        # Separate data to isolate the JSON part
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
        sock.close() # Ensure the socket is closed

def remote_list():
    """
    Sends a LIST command to the server and displays the file list.
    """
    command_str=f"LIST"
    hasil = send_command(command_str)
    # Check if the result is a dict and its status is OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        print("File list:")
        if 'data' in hasil and isinstance(hasil['data'], list):
            for nmfile in hasil['data']:
                print(f"- {nmfile}")
        else:
            print("No files or invalid data format from the server.")
        return True
    else:
        print("Failed to retrieve file list.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Server message: {hasil['data']}")
        return False

def remote_get(filename=""):
    """
    Retrieves a file from the server and saves it locally.
    """
    command_str=f"GET {filename}"
    hasil = send_command(command_str)
    # Check if the result is a dict and its status is OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        namafile = hasil.get('data_namafile')
        isifile_b64 = hasil.get('data_file')

        if not namafile or not isifile_b64:
            print("Server response incomplete (filename or Base64 file content missing).")
            return False

        try:
            isifile = base64.b64decode(isifile_b64)
        except base64.binascii.Error as e:
            print(f"Failed to decode Base64 file content: {e}. Ensure the file is not corrupted.")
            return False

        try:
            with open(namafile,'wb+') as fp:
                fp.write(isifile)
            print(f"File '{namafile}' downloaded successfully.")
            return True
        except Exception as e:
            print(f"Failed to write file '{namafile}': {e}")
            return False
    else:
        print(f"Failed to download file '{filename}'.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Server message: {hasil['data']}")
        return False

def remote_upload(filename=""):
    """
    Uploads a local file to the server after Base64 encoding.
    """
    if not os.path.exists(filename):
        print(f"Error: Local file '{filename}' not found.")
        return False

    try:
        with open(filename, 'rb') as fp:
            file_content = fp.read()
            encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        # Send UPLOAD command with filename and Base64 content
        command_str = f"UPLOAD {filename} {encoded_content}"
        hasil = send_command(command_str)

        # Check if the result is a dict and its status is OK
        if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
            print(f"File '{filename}' uploaded successfully.")
            return True
        else:
            print(f"Failed to upload file '{filename}'.")
            if hasil and isinstance(hasil, dict) and 'data' in hasil:
                print(f"Server message: {hasil['data']}")
            return False
    except Exception as e:
        print(f"Error while uploading file '{filename}': {e}")
        return False

def remote_delete(filename=""):
    """
    Deletes a file on the server.
    """
    command_str = f"DELETE {filename}"
    hasil = send_command(command_str)

    # Check if the result is a dict and its status is OK
    if hasil and isinstance(hasil, dict) and hasil.get('status') == 'OK':
        print(f"File '{filename}' successfully deleted from server.")
        return True
    else:
        print(f"Failed to delete file '{filename}' from server.")
        if hasil and isinstance(hasil, dict) and 'data' in hasil:
            print(f"Server message: {hasil['data']}")
        return False

if __name__=='__main__':
    # Set the server address to match your server's configuration
    server_address=('172.16.16.101',6667) 

    print("--- Listing files ---")
    remote_list()

    # Create a dummy file to upload
    dummy_upload_filename = "upload_test.txt"
    try:
        with open(dummy_upload_filename, 'w') as f:
            f.write("This is a file uploaded from the client.")
        
        print(f"\n--- Uploading '{dummy_upload_filename}' ---")
        remote_upload(dummy_upload_filename)

        print("\n--- Listing files after upload ---")
        remote_list()

        # Retrieve the newly uploaded file
        print(f"\n--- Getting '{dummy_upload_filename}' ---")
        remote_get(dummy_upload_filename)

        # Delete the newly uploaded file
        print(f"\n--- Deleting '{dummy_upload_filename}' ---")
        remote_delete(dummy_upload_filename)

        print("\n--- Listing files after delete ---")
        remote_list()

    finally: 
        # Clean up local dummy files created for upload
        if os.path.exists(dummy_upload_filename):
            os.remove(dummy_upload_filename)
        # Clean up local dummy files that might have been created during 'get' (if they have the same name)
        if os.path.exists(dummy_upload_filename): 
            os.remove(dummy_upload_filename)

    # Example: try to get a file that might already exist on the server
    # print("\n--- Getting 'donalbebek.jpg' (if exists on server) ---")
    # remote_get('donalbebek.jpg')
