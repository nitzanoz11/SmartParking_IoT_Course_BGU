import tkinter as tk
from tkinter import messagebox
import json
import time
import random
import threading
from datetime import datetime
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

# --- Global Configs ---
AWS_HOST = "a3s1kpckywze5x-ats.iot.us-east-1.amazonaws.com"
CLIENT_ID = "ParkingSim_Final_Expanded"
TOPIC_PUB = "parking/updates"
TOPIC_SUB = "parking/cmd"

# certs paths
MY_CERT = "certs/certificate.pem.crt"
MY_KEY = "certs/private.pem.key"
ROOT_CA = "certs/AmazonRootCA1.pem"

# list of employee cars - keeping this hardcoded for now
EMPLOYEE_CARS = [
    "532-12-901", "88-451-23", "601-58-302", "45-920-11", "770-19-405",
    "12-654-89", "332-90-501", "99-123-66", "505-44-112", "67-890-33",
    "202-33-404", "71-234-56", "909-12-888", "15-678-90", "440-55-606",
    "89-012-34", "111-22-333", "23-456-78", "665-77-808", "90-123-45",
    "321-65-498", "54-321-09", "876-54-321", "76-543-21", "102-93-847",
    "19-283-74", "657-48-392", "10-293-84", "847-56-102", "39-485-76",
    "506-17-283"
]

class IoT_Connector:
    # wrapper for the AWS thingy
    def __init__(self, on_msg, on_log):
        self.client = AWSIoTMQTTClient(CLIENT_ID)
        self.client.configureEndpoint(AWS_HOST, 443)
        self.client.configureCredentials(ROOT_CA, MY_KEY, MY_CERT)
        self.client.configureAutoReconnectBackoffTime(1, 32, 20)
        self.client.configureOfflinePublishQueueing(-1)

        self.callback = on_msg
        self.logger = on_log
        self.isConnected = False

    def tryConnect(self):
        try:
            self.logger("Trying to connect to cloud...")
            self.client.connect()
            self.isConnected = True
            
            # sub to command topic
            self.client.subscribe(TOPIC_SUB, 1, self.my_callback)
            self.logger("Connected ok!")
            return True
        except Exception as e:
            self.logger(f"Connect FAIL: {e}")
            return False

    def my_callback(self, client, userdata, msg):
        # decode the payload
        raw = msg.payload.decode('utf-8')
        try:
            obj = json.loads(raw)
            self.callback(obj)
        except:
            print("cant parse json")

    def sendUpdate(self, data):
        if self.isConnected:
            self.client.publish(TOPIC_PUB, json.dumps(data), 1)

class ParkingApp_v2:
    def __init__(self, master):
        self.gui = master
        self.gui.title("Smart Parking System - v2")
        self.gui.geometry("1200x900") 

        self.myCars = list(EMPLOYEE_CARS)
        self.spotMap = {}
        self.gateLabels = {}

        # HEADER
        tk.Label(self.gui, text="Smart Parking System - 3 Floors", font=("Arial", 18, "bold"), pady=10).pack()

        # setup scrollable area
        mainF = tk.Frame(self.gui)
        mainF.pack(fill="both", expand=True, padx=10, pady=5)

        self.cv = tk.Canvas(mainF, bg="#f0f0f0")
        sb = tk.Scrollbar(mainF, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)

        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)

        self.innerFrame = tk.Frame(self.cv, bg="#f0f0f0")
        self.winID = self.cv.create_window((0, 0), window=self.innerFrame, anchor="nw")

        self.innerFrame.bind("<Configure>", self.onConfig)
        self.cv.bind("<Configure>", self.onCanvasConfig)
        self.cv.bind_all("<MouseWheel>", self.doScroll)

        # build the lot
        self.buildGrid(3, 4, 5)

        # bottom controls
        ctrlPanel = tk.Frame(self.gui, bg="#ddd", pady=10, relief="raised")
        ctrlPanel.pack(side="bottom", fill="x")

        self.btnSim = tk.Button(ctrlPanel, text="CAR ARRIVAL",
                                   bg="#2196F3", fg="white", font=("Arial", 12, "bold"),
                                   command=self.carArrives)
        self.btnSim.pack(pady=5)

        self.logBox = tk.Text(ctrlPanel, height=8, bg="black", fg="#00e676", font=("Consolas", 9))
        self.logBox.pack(fill="x", padx=5)

        # init iot
        self.iot = IoT_Connector(self.handleCmd, self.logIt)
        self.gui.after(1000, self.bootUp)

    def bootUp(self):
        if self.iot.tryConnect():
            self.logIt("System Init...")
            # reset all spots
            for s_id, s_data in self.spotMap.items():
                p = {
                    "spot_id": s_id,
                    "status": "RESET",
                    "license_plate": "None",
                    "location": s_data['loc']
                }
                self.iot.sendUpdate(p)
                time.sleep(0.01)  
            self.logIt("Ready to go.")

    def buildGrid(self, floors, r, c):
        # 3 floors, 2 gates on floor 1
        for f in range(1, floors + 1):
            f_frame = tk.Frame(self.innerFrame, pady=10, relief="groove", bd=2)
            f_frame.pack(fill="x", pady=5)

            # left side (gates)
            leftDiv = tk.Frame(f_frame, width=150)
            leftDiv.pack(side="left", fill="y", padx=(0, 20))

            if f == 1:
                tk.Label(leftDiv, text="[ ENTRANCE ]", font=("Arial", 10, "bold")).pack(pady=(10, 5))

                g1 = tk.Label(leftDiv, text="[ GATE-1 ]\nFree", bg="white", fg="black",
                                  width=15, height=3, relief="solid", borderwidth=3)
                g1.pack(pady=5)
                self.gateLabels['GATE-1'] = g1

                g2 = tk.Label(leftDiv, text="[ GATE-2 ]\nFree", bg="white", fg="black",
                                  width=15, height=3, relief="solid", borderwidth=3)
                g2.pack(pady=5)
                self.gateLabels['GATE-2'] = g2
            else:
                tk.Frame(leftDiv, width=150, height=50).pack() # spacer

            # parking grid
            gridBox = tk.LabelFrame(f_frame, text=f"Floor {-f} Parking Area", padx=5, pady=5)
            gridBox.pack(side="left")

            for row in range(r):
                for col in range(c):
                    name = f"F{f}-R{row}-C{col}"
                    l = tk.Label(gridBox, text=f"{name}\n(Free)", width=10, height=3,
                                   bg="#4caf50", fg="white", relief="raised", borderwidth=2)
                    l.grid(row=row, column=col, padx=2, pady=2)
                    
                    self.spotMap[name] = {
                        "ui": l,
                        "status": "free",
                        "loc": {"floor": -f, "row": row, "col": col}
                    }

            # elevator
            elev = tk.Label(gridBox, text="ELEVATOR", width=10, height=3,
                                    bg="#9e9e9e", fg="white", relief="ridge", borderwidth=2)
            elev.grid(row=r-1, column=c, padx=10, pady=2)

    def carArrives(self):
        if len(self.myCars) == 0:
            self.logIt("No more cars!!")
            return

        # pick random car
        idx = random.randint(0, len(self.myCars) - 1)
        plate = self.myCars.pop(idx)

        gid = random.choice(['GATE-1', 'GATE-2'])
        self.logIt(f"--> Car {plate} at {gid}")

        self.gateLabels[gid].config(bg="#f44336", text=f"[{gid}]\nBUSY\n{plate}")

        self.iot.sendUpdate({
            "spot_id": gid,
            "status": "occupied",
            "license_plate": plate
        })
        
        # clear gate after a bit
        self.gui.after(2500, lambda: self.resetGate(gid))

    def resetGate(self, gate):
        self.gateLabels[gate].config(bg="white", text=f"[{gate}]\nFree")
        self.iot.sendUpdate({"spot_id": gate, "status": "free", "license_plate": "None"})

    def handleCmd(self, d):
        cmd = d.get('command')
        sid = d.get('spot_id')
        lp = d.get('license_plate')
        t_time = d.get('travel_time', 2.0)

        if cmd == 'reserve' and sid in self.spotMap:
            self.logIt(f"<< Reserved {sid}. Time: {t_time}s")
            self.setSpotState(sid, "reserved", lp)
            
            # simulate driving
            threading.Thread(target=self.doDrive, args=(sid, lp, t_time)).start()
            
            # timeout checker
            threading.Timer(60.0, self.checkTimeout, args=(sid,)).start()

    def doDrive(self, targetSpot, plate, waitTime):
        print(f"DEBUG: Driving {plate} to {targetSpot}...")
        time.sleep(waitTime)

        rnd = random.random()
        finalLoc = targetSpot

        # VIP logic for that specific plate
        if plate and str(plate).strip() == "111-22-333":
            self.logIt(f"VIP DETECTED! Use special spot.")
            finalLoc = "F2-R0-C0"

            # release old if changed
            if finalLoc != targetSpot:
                self.setSpotState(targetSpot, "free")
                self.iot.sendUpdate({
                    "spot_id": targetSpot,
                    "status": "free",
                    "license_plate": "None",
                    "location": self.spotMap[targetSpot]['loc']
                })

            self.setSpotState(finalLoc, "occupied", plate)
            self.iot.sendUpdate({
                "spot_id": finalLoc,
                "status": "occupied",
                "license_plate": plate,
                "location": self.spotMap[finalLoc]['loc']
            })
            return

        if rnd < 0.2:
            # rogue driver logic
            frees = [k for k,v in self.spotMap.items() if v['status'] == 'free' and k != targetSpot]
            if frees:
                finalLoc = random.choice(frees)
                self.logIt(f"ROGUE DRIVER! Stealing {finalLoc}")
            else:
                self.logIt("Rogue failed, no spots.")

        # update final
        self.setSpotState(finalLoc, "occupied", plate)
        self.iot.sendUpdate({
            "spot_id": finalLoc,
            "status": "occupied",
            "license_plate": plate,
            "location": self.spotMap[finalLoc]['loc']
        })

    def checkTimeout(self, s_id):
        curr = self.spotMap[s_id]['status']
        if curr == 'reserved':
            self.logIt(f"TIMEOUT: {s_id} expired.")
            self.setSpotState(s_id, "free")
            self.iot.sendUpdate({
                "spot_id": s_id,
                "status": "free",
                "license_plate": "None",
                "location": self.spotMap[s_id]['loc']
            })

    def setSpotState(self, sid, st, p=""):
        if sid not in self.spotMap: return

        obj = self.spotMap[sid]
        obj['status'] = st
        w = obj['ui']

        c = "#4caf50" # green
        t = f"{sid}\n(Free)"

        if st == 'occupied':
            c = "#f44336"
            t = f"{sid}\nOccupied"
        elif st == 'reserved':
            c = "#ff9800"
            t = f"{sid}\nReserved"

        self.gui.after(0, lambda: w.config(bg=c, text=t))

    def logIt(self, txt):
        now = datetime.now().strftime("%H:%M:%S")
        self.gui.after(0, lambda: self.logBox.insert(tk.END, f"[{now}] {txt}\n"))
        self.gui.after(0, lambda: self.logBox.see(tk.END))

    # scroll stuff
    def onConfig(self, e):
        self.cv.configure(scrollregion=self.cv.bbox("all"))

    def onCanvasConfig(self, e):
        self.cv.itemconfig(self.winID, width=e.width)

    def doScroll(self, e):
        self.cv.yview_scroll(int(-1 * (e.delta / 120)), "units")


if __name__ == "__main__":
    top = tk.Tk()
    app = ParkingApp_v2(top)
    top.mainloop()