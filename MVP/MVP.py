import tkinter as tk
import mido
import threading
import RPi.GPIO as GPIO
import time
from adafruit_pca9685 import PCA9685
from board import SCL, SDA
import busio
from adafruit_motor import servo
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from pythonosc import udp_client

# ==== OSC Send Function ====
def send_osc(address):
    try:
        IP = "192.168.254.12"
        PORT = 8000
        client = udp_client.SimpleUDPClient(IP, PORT)
        client.send_message(address, float(1))
        print(f"OSC sent: {address}")
    except Exception as e:
        print(f"Failed to send OSC {address}: {e}")

def send_gma3_command(cmd_string: str):
    try:
        IP = "192.168.254.213"
        PORT = 2000
        addr = "/gma3/cmd"
        client = udp_client.SimpleUDPClient(IP, PORT)
        client.send_message(addr, cmd_string)
        print(f"GMA3 Command Sent: {cmd_string}")
    except Exception as e:
        print(f"Failed to send to grandMA3: {e}")

# ==== Servo Setup ====
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c, address=0x43)
pca.frequency = 50
servos = [servo.Servo(pca.channels[i]) for i in range(16)]

# ==== Laser Setup ====
LASERS = {1: 17}  # Only GPIO17 connected
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in LASERS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.HIGH)

# ==== ADC Setup ====
adc = ADS.ADS1115(i2c, address=0x48)
channels_adc = [AnalogIn(adc, ADS.P0), AnalogIn(adc, ADS.P1), AnalogIn(adc, ADS.P2), AnalogIn(adc, ADS.P3)]

# ==== Base Stage Class ====
class StageBase:
    def __init__(self, app, name):
        self.app = app
        self.name = name

    def on_enter(self): pass
    def on_start(self): pass
    def on_win(self): pass
    def on_lose(self): pass

# ==== Individual Stages ====
class Stage1(StageBase):
    def on_enter(self):
        send_gma3_command("Off Sequence 11")
        send_gma3_command("Go+ Sequence 4")
        send_gma3_command("Go+ Sequence 6")
        send_gma3_command("Go+ Sequence 12")

    def on_start(self):
        send_osc("/action/40162")
        send_gma3_command("Off Sequence 2")
        send_gma3_command("Off Sequence 3")
        send_gma3_command("Off Sequence 4")
        send_gma3_command("Off Sequence 6")
        send_gma3_command("Off Sequence 12")
        send_gma3_command("Go+ Sequence 7")
        send_gma3_command("Go+ Sequence 9")
        GPIO.output(LASERS[1], GPIO.LOW)

    def on_win(self):
        send_osc("/action/40168")
        send_gma3_command("Off Sequence 9")
        send_gma3_command("Go+ Sequence 3")

    def on_lose(self):
        send_osc("/action/40164")
        send_gma3_command("Off Sequence 9")
        send_gma3_command("Go+ Sequence 2")

class Stage2(StageBase):
    def on_enter(self):
        send_gma3_command("Off Sequence 11")
        send_gma3_command("Go+ Sequence 4")
        send_gma3_command("Go+ Sequence 6")
        send_gma3_command("Go+ Sequence 12")

    def on_start(self):
        send_osc("/action/40169")
        send_gma3_command("Off Sequence 4")
        send_gma3_command("Off Sequence 6")
        send_gma3_command("Off Sequence 12")
        send_gma3_command("Go+ Sequence 7")
        send_gma3_command("Go+ Sequence 9")
        GPIO.output(LASERS[1], GPIO.LOW)

    def on_win(self):
        send_osc("/action/40165")
        send_gma3_command("Off Sequence 9")
        send_gma3_command("Go+ Sequence 3")
        send_gma3_command("Go+ Sequence 5")
        send_gma3_command("Go+ Sequence 8")

    def on_lose(self):
        send_osc("/action/40164")
        send_gma3_command("Off Sequence 9")
        send_gma3_command("Go+ Sequence 2")

# ==== Stage and Pad Mapping ====
PAD_TO_STAGE = {
    36: Stage1,
    37: Stage2,
}
STAGE_DURATIONS = {
    "Stage1": 30,
    "Stage2": 45
}

START_BUTTON_PAD = 45
RESTART_BUTTON_PAD = 46
STOP_PAD = 47
START_PAD = 39
CONTROLLED_SERVOS = {24: 13, 26: 4, 27: 15}
sweep_pairs = [[1, 6], [7, 10], [11, 8]]

# ==== App Class ====
class StageDisplayApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Stage Display")
        self.root.attributes("-fullscreen", True)

        self.label = tk.Label(self.root, text="Select a stage", font=("Arial", 80))
        self.label.pack(expand=True)

        self.current_stage = None
        self.timer_running = False
        self.timer_id = None
        self.light_thread = None
        self.sweep_thread = None
        self.sweep_flag = threading.Event()
        self.win_detected = False

    def show_stage(self, stage_class):
        if not self.timer_running:
            self.current_stage = stage_class(self, stage_class.__name__)
            self.label.config(text=self.current_stage.name)
            self.current_stage.on_enter()

    def start_timer(self):
        if self.current_stage and not self.timer_running:
            self.current_stage.on_start()
            duration = STAGE_DURATIONS.get(self.current_stage.name, 30)
            self.win_detected = False
            self.timer_running = True
            self.run_countdown(duration)
            self.sweep_flag.set()
            self.sweep_thread = threading.Thread(target=self.sweep_servos_loop, daemon=True)
            self.sweep_thread.start()
            self.light_thread = threading.Thread(target=self.monitor_lights, daemon=True)
            self.light_thread.start()

    def run_countdown(self, seconds_left):
        if seconds_left > 0 and self.timer_running and not self.win_detected:
            self.label.config(text=f"{self.current_stage.name}\n{seconds_left} sec")
            self.timer_id = self.root.after(1000, self.run_countdown, seconds_left - 1)
        elif not self.win_detected:
            self.end_stage("LOSE", lose=True)

    def end_stage(self, message, win=False, lose=False):
        self.timer_running = False
        GPIO.output(list(LASERS.values()), GPIO.LOW)

        if win:
            self.current_stage.on_win()
        elif lose:
            self.current_stage.on_lose()

        self.label.config(text=message)
        self.timer_id = self.root.after(3000, self.reset_display)
        self.sweep_flag.clear()

    def reset_display(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.label.config(text="Select a stage")
        self.timer_running = False
        self.current_stage = None
        self.win_detected = False
        for pin in LASERS.values():
            GPIO.output(pin, GPIO.HIGH)
        self.sweep_flag.clear()

    def monitor_lights(self):
        WIN_THRESHOLD = 2.6
        WIN_DURATION = 1.0
        light_sensor = channels_adc[0]
        start_time = None

        while self.timer_running and not self.win_detected:
            voltage = light_sensor.voltage
            print(f"Sensor voltage: {voltage:.2f}V")

            if voltage > WIN_THRESHOLD:
                if start_time is None:
                    start_time = time.time()
                elif time.time() - start_time >= WIN_DURATION:
                    self.win_detected = True
                    self.end_stage("WIN", win=True)
                    return
            else:
                start_time = None
            time.sleep(0.1)

    def sweep_servos_loop(self):
        try:
            while self.sweep_flag.is_set():
                for pair in sweep_pairs:
                    servos[pair[0]].angle = 0
                    servos[pair[1]].angle = 0
                    time.sleep(0.5)
                time.sleep(1)
                for pair in sweep_pairs:
                    servos[pair[0]].angle = 90
                    servos[pair[1]].angle = 90
                    time.sleep(0.5)
                time.sleep(1)
        except Exception as e:
            print(f"Sweep thread error: {e}")

# ==== MIDI Listener ====
def midi_listener(app):
    input_name = None
    for name in mido.get_input_names():
        if "MPD218" in name:
            input_name = name
            break

    if not input_name:
        print("MPD218 not found.")
        return

    with mido.open_input(input_name) as port:
        for msg in port:
            if msg.type == 'note_on' and msg.velocity > 0:
                note = msg.note
                if note in PAD_TO_STAGE:
                    stage_class = PAD_TO_STAGE[note]
                    app.root.after(0, app.show_stage, stage_class)
                elif note == START_BUTTON_PAD:
                    app.root.after(0, app.start_timer)
                elif note == RESTART_BUTTON_PAD:
                    app.root.after(0, app.reset_display)
                    send_osc("/action/40167")
                elif note == START_PAD:
                    send_osc("/action/40161")
                    send_osc("/action/1007")
                elif note == STOP_PAD:
                    send_osc("/action/1016")

            elif msg.type == 'control_change':
                cc = msg.control
                val = msg.value
                if cc in CONTROLLED_SERVOS:
                    angle = int(val * 180 / 127)
                    servos[CONTROLLED_SERVOS[cc]].angle = angle

# ==== Main Entry Point ====
if __name__ == "__main__":
    root = tk.Tk()
    app = StageDisplayApp(root)
    midi_thread = threading.Thread(target=midi_listener, args=(app,), daemon=True)
    midi_thread.start()
    root.mainloop()
