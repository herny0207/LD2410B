import serial_protocol

import serial

# Open the serial port (Windows: 'COM3', 'COM4', etc. | Linux: '/dev/ttyUSB0')
COM_PORT = 'COM3' # TODO: 請根據您的「裝置管理員」中的 COM 序列埠進行修改
ser = serial.Serial(COM_PORT, 256000, timeout=1)

try:
    while True:
        # Read a line from the serial port
        serial_port_line = ser.read_until(b'\xF8\xF7\xF6\xF5')
        target_values = serial_protocol.read_basic_mode(serial_port_line)
        
        # if line is corrupted, skip it
        if target_values is None:
            if len(serial_port_line) > 0:
                print(f"收到無法解析的原始資料 (長度: {len(serial_port_line)}): {serial_port_line.hex()[:50]}...")
            continue

        target_state, \
        moving_target_dist, moving_target_energy, \
        static_target_dist, static_target_energy, \
        distance \
            = target_values

                    
        print('Target State:', target_state)
        print('Moving Target Distance:', moving_target_dist)
        print('Moving Target Energy:', moving_target_energy)
        print('Static Target Distance:', static_target_dist)
        print('Static Target Energy:', static_target_energy)
        print('Distance:', distance)
        print()
        print(30*'-')
        print()

except KeyboardInterrupt:
    # Close the serial port on keyboard interrupt
    ser.close()
    print("Serial port closed.")