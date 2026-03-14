import os
import sys
import binascii
import struct
import zlib
import io
from io import BytesIO
import ctypes
import datetime
from ctypes import (
    c_char_p,
    c_size_t,
    POINTER,
    create_string_buffer,
    c_int,
    CDLL,
    byref,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

# Platform-specific imports for Windows file time handling
try:
    import pywintypes
    import win32file
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

# Global LZO DLL variables
lzo_compress = None
lzo_decompress = None


def load_dlls():
    """Load the appropriate LZO DLLs based on system architecture"""
    global lzo_compress, lzo_decompress
    
    is_64bit = sys.maxsize > 2**32
    
    # Get the directory where the exe/script is located
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        app_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    dll_c_name = 'minilzo_c_x64.dll' if is_64bit else 'minilzo_c_x86.dll'
    dll_d_name = 'minilzo_d_x64.dll' if is_64bit else 'minilzo_d_x86.dll'
    
    dll_c_path = os.path.join(app_dir, dll_c_name)
    dll_d_path = os.path.join(app_dir, dll_d_name)
    
    # Try generic names if specific not found
    if not os.path.exists(dll_c_path):
        dll_c_path = os.path.join(app_dir, 'minilzo_c.dll')
    if not os.path.exists(dll_d_path):
        dll_d_path = os.path.join(app_dir, 'minilzo_d.dll')
    
    try:
        lzo_compress = CDLL(dll_c_path)
        lzo_compress.lzo1x_compress_simple.argtypes = [
            c_char_p, c_size_t, c_char_p, POINTER(c_size_t)
        ]
        lzo_compress.lzo1x_compress_simple.restype = c_int
    except Exception as e:
        print(f"ERROR: Could not load compression DLL: {dll_c_name}")
        print(f"Error: {e}")
        return False
    
    try:
        lzo_decompress = CDLL(dll_d_path)
        lzo_decompress.lzo_decompress.argtypes = [
            c_char_p, c_size_t, c_char_p, POINTER(c_size_t)
        ]
        lzo_decompress.lzo_decompress.restype = c_int
    except Exception as e:
        print(f"ERROR: Could not load decompression DLL: {dll_d_name}")
        print(f"Error: {e}")
        return False
    
    return True


def compress_lzo(data: bytes) -> bytes:
    src_len = len(data)
    dst_len = c_size_t(src_len + src_len // 16 + 64 + 3)
    dst_buf = create_string_buffer(dst_len.value)

    result = lzo_compress.lzo1x_compress_simple(
        c_char_p(data),
        src_len,
        dst_buf,
        byref(dst_len)
    )

    if result != 0:
        raise RuntimeError(f"LZO compression failed (code {result})")

    return dst_buf.raw[:dst_len.value]


def decompress_lzo(src_data: bytes, expected_size: int) -> bytes:
    src_len = len(src_data)
    dst_len = c_size_t(expected_size)
    dst_buf = create_string_buffer(expected_size)

    result = lzo_decompress.lzo_decompress(
        c_char_p(src_data),
        src_len,
        dst_buf,
        byref(dst_len)
    )
    if result != 0:
        raise RuntimeError(f"LZO decompression failed (code {result})")

    return dst_buf.raw[:dst_len.value]


def filetime_to_datetime(filetime_int):
    return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime_int // 10)


def set_creation_time(file_path, filetime_value):
    if not WINDOWS_AVAILABLE:
        return
    
    try:
        dt = filetime_to_datetime(filetime_value)
        wintime = pywintypes.Time(dt)
        handle = win32file.CreateFile(
            file_path, win32file.GENERIC_WRITE, 0, None,
            win32file.OPEN_EXISTING, 0, None
        )
        win32file.SetFileTime(handle, wintime, None, wintime)
        handle.close()
    except:
        pass


def format_size(size_in_bytes):
    size_in_bytes = int(size_in_bytes)
    if size_in_bytes >= 1_048_576:
        return f"{size_in_bytes / 1_048_576:.2f} MB"
    else:
        return f"{size_in_bytes / 1024:.2f} KB"


def chunk_size_value(size, max_chunk_size):
    if size == max_chunk_size:
        size = 0
    return size


def pack_offset_and_flag(offset: int, flag: int) -> bytes:
    offset_bytes = offset.to_bytes(3, byteorder="little")
    flag_byte = struct.pack("<B", flag)
    return offset_bytes + flag_byte


def decompress_file_worker(args):
    """Worker function for parallel decompression - reads its own file handle"""
    file_index, metadata, pak_filename, output_path, max_chunk_size = args
    
    try:
        # Each worker opens its own file handle for thread safety
        with open(pak_filename, 'rb', buffering=1024*1024) as f:
            f.seek(metadata['file_offset'])
            
            # Pre-allocate list for chunks
            file_data_parts = []
            
            for header in metadata['chunk_headers']:
                chunk_size = header[0]
                compression_flag = header[1]
                
                if compression_flag == 65535:
                    chunk_size = 65536 - chunk_size
                    chunk_data = f.read(chunk_size)
                    file_data_parts.append(chunk_data)
                else:
                    if chunk_size == 0:
                        chunk_size = max_chunk_size
                    chunk_data = f.read(chunk_size)
                    file_data_parts.append(decompress_lzo(chunk_data, max_chunk_size))
            
            # Join all chunks at once
            file_data = b''.join(file_data_parts)
        
        # Create output directory if needed
        directory_path = os.path.dirname(output_path)
        if directory_path and not os.path.exists(directory_path):
            os.makedirs(directory_path, exist_ok=True)
        
        # Write file with larger buffer
        with open(output_path, 'wb', buffering=1024*1024) as out_f:
            out_f.write(file_data)
        
        # Set creation time
        set_creation_time(output_path, metadata['creation_date'])
        
        return True, metadata['path']
    except Exception as e:
        return False, f"{metadata['path']}: {str(e)}"


def unpack_pak(input_file, output_path, use_parallel=True):
    """Unpack a PAK file with optional parallel processing"""
    print(f"\n=== UNPACKING: {os.path.basename(input_file)} ===\n")
    
    max_chunk_size = 65536
    
    with open(input_file, 'rb') as f:
        if f.read(4) != b'PAK!':
            print('ERROR: Not a PAK file.')
            return False
        
        version = struct.unpack("<I", f.read(4))[0]
        if version != 4:
            print(f'ERROR: PAK file is version {version}, expected version 4.')
            return False
        
        offset_to_metadata = struct.unpack("<I", f.read(4))[0]
        
        f.seek(offset_to_metadata)
        metadata_size = struct.unpack("<I", f.read(4))[0]
        f.seek(offset_to_metadata + metadata_size)
        number_of_chunks = struct.unpack("<I", f.read(4))[0]
        
        chunk_headers = io.BytesIO(f.read())
        f.seek(offset_to_metadata)
        
        decompressed_data = b''
        last_offset = 0
        last_decompressed_size = 0
        
        print("Decompressing metadata...")
        # Use list for accumulation
        metadata_parts = []
        for n in range(number_of_chunks):
            decompressed_size = struct.unpack("<I", chunk_headers.read(4))[0]
            second_header_part = chunk_headers.read(4)
            offset = struct.unpack("<I", second_header_part[:3] + b'\x00')[0]
            _data_ = f.read(offset - last_offset)
            if decompressed_size != last_decompressed_size:
                try:
                    decompressed = zlib.decompress(_data_)
                    metadata_parts.append(decompressed)
                except Exception as e:
                    print(f'WARNING: Decompression failed for chunk {n}: {e}')
            last_offset = offset
            last_decompressed_size = decompressed_size
        
        decompressed_data = b''.join(metadata_parts)
        
        metadata = io.BytesIO(decompressed_data)
        marker = struct.unpack("<B", metadata.read(1))[0]
        number_of_files = struct.unpack("<I", metadata.read(4))[0]
        
        if number_of_files == 0:
            print('ERROR: No files in the PAK archive.')
            return False
        
        print(f"Found {number_of_files} files\n")
        
        metadata_dict = {}
        for n in range(number_of_files):
            metadata_dict[n] = {}
            metadata_dict[n]['file_offset'] = struct.unpack("<I", metadata.read(4))[0]
            file_size = struct.unpack("<I", metadata.read(4))[0]
            metadata_dict[n]['file_size'] = file_size
            metadata_dict[n]['file_name_hash'] = struct.unpack("<I", metadata.read(4))[0]
            
            file_chunks = file_size // max_chunk_size
            last_chunk = file_size % max_chunk_size
            if last_chunk != 0:
                file_chunks += 1
            
            metadata_dict[n]['chunk_headers'] = []
            for _ in range(file_chunks):
                metadata_dict[n]['chunk_headers'].append(struct.unpack("<HH", metadata.read(4)))
        
        for n in range(number_of_files):
            creation_date = struct.unpack("<Q", metadata.read(8))[0]
            path_len = struct.unpack("<B", metadata.read(1))[0]
            path = metadata.read(path_len).decode('utf-8')
            
            metadata_dict[n]['creation_date'] = creation_date
            metadata_dict[n]['path'] = path
    
    # Prepare worker arguments
    worker_args = []
    for n in range(number_of_files):
        full_output_path = os.path.join(output_path, metadata_dict[n]['path'].lstrip("\\/"))
        worker_args.append((n, metadata_dict[n], input_file, full_output_path, max_chunk_size))
    
    # Use parallel processing for decompression
    if use_parallel and number_of_files > 4:
        # Use ALL CPU cores for maximum speed
        max_workers = min(multiprocessing.cpu_count(), number_of_files)
        print(f"Using {max_workers} parallel workers\n")
        
        success_count = 0
        # Suppress individual file output for speed, just show count
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(decompress_file_worker, args) for args in worker_args]
            
            for future in as_completed(futures):
                success, result = future.result()
                if success:
                    success_count += 1
                    # Only print every 10th file or last file for speed
                    if success_count % 10 == 0 or success_count == number_of_files:
                        print(f"Progress: {success_count}/{number_of_files} files extracted")
                else:
                    print(f"ERROR: {result}")
    else:
        # Sequential processing
        success_count = 0
        for args in worker_args:
            success, result = decompress_file_worker(args)
            if success:
                success_count += 1
                print(f"[{success_count}/{number_of_files}] {result} ({format_size(args[1]['file_size'])})")
            else:
                print(f"ERROR: {result}")
    
    print(f"\n✓ Successfully unpacked {success_count}/{number_of_files} files to: {output_path}\n")
    return True


def pack_pak(input_folder, output_file, use_compression=True, use_parallel=False):
    """
    Pack a folder into a PAK file - Fixed to match original pack.py logic
    Note: Parallel processing disabled for packing to maintain correct file order and chunking
    """
    print(f"\n=== PACKING: {os.path.basename(input_folder)} ===\n")
    
    file_extensions_uncompressed = ('.vso', '.pso', '.rs', '.bik')
    max_chunk_size = 65536
    
    meta_part_1 = bytearray()  # Use bytearray for faster append
    meta_part_2 = bytearray()
    file_count = 0
    
    file_chunks_storage = io.BytesIO()
    chunks_counter = 0
    
    header = b'PAK!' + struct.pack('<I', 4)
    # Larger write buffer for speed
    pak_file = open(output_file, 'wb', buffering=2*1024*1024)
    pak_file.write(header)
    pak_file.write(struct.pack("<I", 0))  # Placeholder for metadata offset
    offset_to_metadata = len(header) + 4
    
    # Gather all files first
    all_files = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            all_files.append(os.path.join(root, file))
    
    if not all_files:
        print("ERROR: No files found to pack.")
        pak_file.close()
        return False
    
    # Sort to ensure consistent order
    all_files.sort()
    
    print(f"Found {len(all_files)} files to pack\n")
    
    # Process each file
    for file_idx, file_path in enumerate(all_files):
        try:
            file_size = os.path.getsize(file_path)
            
            # Windows FILETIME
            filetime = int((os.path.getctime(file_path) + 11644473600) * 10**7)
            
            file_path_in_pak = os.path.relpath(file_path, input_folder)
            
            pack_file_uncompressed = file_path_in_pak.lower().endswith(file_extensions_uncompressed)
            
            file_path_in_pak_bytes = file_path_in_pak.encode()
            crc32_hash = binascii.crc32(file_path_in_pak_bytes)
            
            first_chunk = True
            
            # Larger read buffer
            with open(file_path, 'rb', buffering=1024*1024) as f:
                while True:
                    chunk = f.read(max_chunk_size)
                    if not chunk:
                        break
                    
                    chunk_size = len(chunk)
                    
                    if first_chunk:
                        # Write metadata for this file (using extend on bytearray is fast)
                        meta_part_1.extend(struct.pack("<I", offset_to_metadata))
                        meta_part_1.extend(struct.pack("<I", file_size))
                        meta_part_1.extend(struct.pack("<I", crc32_hash))
                        
                        meta_part_2.extend(struct.pack('<Q', filetime))
                        meta_part_2.extend(struct.pack("<B", len(file_path_in_pak_bytes)))
                        meta_part_2.extend(file_path_in_pak_bytes)
                        
                        first_chunk = False
                        file_count += 1
                    
                    # Compress and write chunk
                    if use_compression and not pack_file_uncompressed:
                        compressed_chunk = compress_lzo(chunk)
                        compressed_chunk_size = len(compressed_chunk)
                        if compressed_chunk_size < chunk_size:
                            # Use compressed version
                            meta_part_1.extend(struct.pack("<HH", compressed_chunk_size, 0))
                            file_chunks_storage.write(compressed_chunk)
                            chunks_counter += 1
                            offset_to_metadata += compressed_chunk_size
                        else:
                            # Compressed is bigger, use uncompressed
                            if chunk_size <= max_chunk_size:
                                meta_part_1.extend(struct.pack("<HH", chunk_size_value(max_chunk_size - chunk_size, max_chunk_size), 65535))
                            file_chunks_storage.write(chunk)
                            chunks_counter += 1
                            offset_to_metadata += chunk_size
                    else:
                        # Don't compress
                        meta_part_1.extend(struct.pack("<HH", chunk_size_value(max_chunk_size - chunk_size, max_chunk_size), 65535))
                        file_chunks_storage.write(chunk)
                        chunks_counter += 1
                        offset_to_metadata += chunk_size
                    
                    # Write chunks in batches to avoid memory issues
                    if chunks_counter >= 2000:
                        chunks_counter = 0
                        pak_file.write(file_chunks_storage.getvalue())
                        pak_file.flush()
                        file_chunks_storage = io.BytesIO()
            
            # Only print every 10th file for speed
            if (file_idx + 1) % 10 == 0 or (file_idx + 1) == len(all_files):
                print(f"Progress: {file_idx + 1}/{len(all_files)} files packed")
            
        except Exception as e:
            print(f"ERROR processing {file_path}: {e}")
            continue
    
    # Write remaining chunks
    if len(file_chunks_storage.getvalue()) > 0:
        pak_file.write(file_chunks_storage.getvalue())
        pak_file.flush()
    file_chunks_storage.close()
    
    if file_count > 0:
        print("\nCompressing metadata...")
        # Compress and write metadata
        uncompressed_metadata = struct.pack("<B", 1)
        uncompressed_metadata += struct.pack("<I", file_count) + bytes(meta_part_1) + bytes(meta_part_2)
        
        stream = BytesIO(uncompressed_metadata)
        decompressed_size = 0
        chunk_headers = struct.pack("<I", 0) + pack_offset_and_flag(4, 128)
        chunk_end_offset = 4
        chunk_headers_count = 1
        
        # Compress metadata in chunks
        compressed_parts = []
        while True:
            chunk = stream.read(max_chunk_size)
            if not chunk:
                break
            decompressed_size += len(chunk)
            compressed_chunk = zlib.compress(chunk, level=1)  # Fastest compression for metadata
            compressed_parts.append(compressed_chunk)
            chunk_end_offset += len(compressed_chunk)
            chunk_headers += struct.pack("<I", decompressed_size) + pack_offset_and_flag(chunk_end_offset, 128)
            chunk_headers_count += 1
        
        compressed_metadata = b''.join(compressed_parts)
        complete_meta_part = struct.pack("<I", len(compressed_metadata) + 4) + compressed_metadata + struct.pack("<I", chunk_headers_count) + chunk_headers
        
        pak_file.write(complete_meta_part)
        
        # Update metadata offset
        pak_file.seek(8)
        pak_file.write(struct.pack("<I", offset_to_metadata))
        pak_file.flush()
        pak_file.close()
        
        print(f"\n✓ Successfully packed to: {output_file}\n")
        return True
    else:
        pak_file.close()
        print('ERROR: No files to pack.')
        return False

def main():
    print("=" * 60)
    print("  PAK File Tool - Unpack/Repack (Optimized)")
    print("=" * 60)
    
    # Detect architecture
    is_64bit = sys.maxsize > 2**32
    print(f"System: {'64-bit' if is_64bit else '32-bit'}")
    print(f"CPU Cores: {multiprocessing.cpu_count()}")
    
    # Load DLLs
    if not load_dlls():
        print("\nERROR: Failed to load LZO DLLs.")
        print("Make sure the DLL files are in the same folder as this program.")
        return
    
    print("DLLs loaded successfully\n")
    
    # Check if file was dragged onto exe
    if len(sys.argv) < 2:
        print("Usage:")
        print("  - Drag and drop a .pak file to UNPACK it")
        print("  - Drag and drop a folder to PACK it into a .pak file")
        return
    
    input_path = sys.argv[1]
    
    if not os.path.exists(input_path):
        print(f"ERROR: Path does not exist: {input_path}")
        return
    
    # Check if it's a file or folder
    if os.path.isfile(input_path):
        # UNPACK mode
        if not input_path.lower().endswith('.pak'):
            print("ERROR: File must be a .pak file")
            return
        
        # Create output folder (same name as pak file without extension)
        output_folder = os.path.splitext(input_path)[0]
        
        if os.path.exists(output_folder):
            response = input(f"\nFolder '{output_folder}' already exists. Overwrite? (y/n): ")
            if response.lower() != 'y':
                print("Operation cancelled.")
                return
        
        os.makedirs(output_folder, exist_ok=True)
        
        success = unpack_pak(input_path, output_folder, use_parallel=True)
        
    elif os.path.isdir(input_path):
        # PACK mode
        # Create output pak file
        output_pak = input_path.rstrip("\\/") + ".pak"
        
        if os.path.exists(output_pak):
            response = input(f"\nFile '{output_pak}' already exists. Overwrite? (y/n): ")
            if response.lower() != 'y':
                print("Operation cancelled.")
                return
        
        success = pack_pak(input_path, output_pak, use_compression=True, use_parallel=False)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()