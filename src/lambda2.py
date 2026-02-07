import json
import boto3
import time
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
import base64 # unused but keeping it cause who knows

# --- Configs & Consts ---
SNS_TOPIC = "arn:aws:sns:us-east-1:856221043008:ParkingNotifications"
BUCKET = "smart-parking-app-nitzan-daniel"
SECRET = "MySuperSecretProjectKey"

# multipliers
DRIVE_MULT = 1.0
WALK_MULT = 4.5
FLOOR_PENALTY = 6.0
PARK_TIME = 5.0

# map positions
GATE_COORDS = {"row": 0, "col": 0}
ELEVATOR_COORDS = {"row": 2, "col": 4}

# dynamo setup
dynamo = boto3.resource('dynamodb')
tbl_spots = dynamo.Table('SmartParking_Spots')
tbl_users = dynamo.Table('SmartParking_Employees')

# other clients
iot = boto3.client('iot-data')
s3 = boto3.client('s3')
ses = boto3.client('ses')

def helper_decimal(o):
    if isinstance(o, Decimal):
        return int(o)
    return o

def notify_driver(email, name, spot_id, floor_num):
    # sends email via SES
    SENDER = "dansadovnik97@gmail.com"
    subject = f"Parking Spot Assigned: {spot_id}"
    
    # building the message manually
    msg = "Hello " + name + ",\n\n"
    msg += "Welcome back!\n"
    msg += "Our system has assigned you an optimal parking spot.\n\n"
    msg += f"Your Spot: {spot_id}\n"
    msg += "Floor: " + str(floor_num) + "\n\n"
    msg += "Please drive safely."

    print(f"DEBUG: sending email to {email}")
    try:
        res = ses.send_email(
            Source=SENDER,
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': msg}}
            }
        )
        print("Email sent! ID:", res['MessageId'])
    except Exception as e:
        print("failed to send email:", e)

def refresh_s3_json():
    # updates the public json on S3 for the web view
    print("updating s3...")
    try:
        resp = tbl_spots.scan()
        data = resp.get('Items', [])
        
        # current state
        state = {
            "last_updated": int(time.time()),
            "spots": []
        }

        for d in data:
            try:
                l = d.get('location', {})
                if not l: continue

                obj = {
                    "spot_id": str(d.get('spot_id', 'Unknown')),
                    "status": str(d.get('status', 'free')),
                    "floor": int(l.get('floor', 0)),
                    "row": int(l.get('row', 0)),
                    "col": int(l.get('col', 0))
                }
                state["spots"].append(obj)
            except:
                pass # skip bad data

        # upload to bucket
        s3.put_object(
            Bucket=BUCKET,
            Key='parking_data2.json',
            Body=json.dumps(state, default=helper_decimal),
            ContentType='application/json',
            CacheControl='no-cache, no-store, must-revalidate'
        )
        print("s3 updated ok")
    except Exception as e:
        print("S3 ERROR:", e)

def get_spot_score(s):
    try:
        loc = s.get('location', {})
        f = int(loc.get('floor', 0))
        r = int(loc.get('row', 0))
        c = int(loc.get('col', 0))

        # distance calcs
        d_drive = abs(r - GATE_COORDS['row']) + abs(c - GATE_COORDS['col'])
        t_drive = (d_drive * DRIVE_MULT) + (abs(f) * FLOOR_PENALTY)
        
        d_walk = abs(r - ELEVATOR_COORDS['row']) + abs(c - ELEVATOR_COORDS['col'])
        t_walk = d_walk * WALK_MULT
        
        # total cost is time to drive + time to walk + parking
        total = t_drive + t_walk + PARK_TIME
        sim = t_drive + PARK_TIME
        
        return total, sim
    except:
        return 9999, 10 # return bad score if error

def lambda_handler(event, context):
    print("EVENT:", event)
    
    sid = event.get('spot_id')
    status = event.get('status')
    lp = event.get('license_plate') # lp = license plate

    try:
        if status == 'RESET':
            print("Resetting spot", sid)
            tbl_spots.put_item(Item={
                'spot_id': sid, 
                'status': 'free', 
                'license_plate': 'None', 
                'driver': 'None', 
                'location': event.get('location')
            })

        elif 'GATE' in sid and status == 'occupied':
            # car just entered
            print("Car at gate...")
            
            # get all free spots
            scan = tbl_spots.scan(FilterExpression=Attr('status').eq('free'))
            free_spots = scan.get('Items', [])
            
            if free_spots:
                # score them all
                scores = []
                for s in free_spots:
                    sc, st = get_spot_score(s)
                    scores.append((sc, st, s))
                
                # pick best
                best = min(scores, key=lambda x: x[0])
                
                best_id = best[2]['spot_id']
                sim_time = best[1]
                best_floor = best[2]['location']['floor']

                # check if we know the user
                d_name = "Guest"
                d_email = None
                
                try:
                    user_res = tbl_users.get_item(Key={'license_plate': lp})
                    if 'Item' in user_res:
                        d_name = user_res['Item'].get('name', 'Guest')
                        d_email = user_res['Item'].get('email')
                except Exception as e:
                    print("db error", e)

                # notify if email exists
                if d_email:
                    notify_driver(d_email, d_name, best_id, best_floor)
                else:
                    print("no email for user, skipping notify")

                # reserve the spot
                tbl_spots.update_item(
                    Key={'spot_id': best_id},
                    UpdateExpression="set #s=:s, #l=:l, #d=:d",
                    ExpressionAttributeNames={'#s': 'status', '#l': 'license_plate', '#d': 'driver'},
                    ExpressionAttributeValues={':s': 'reserved', ':l': lp, ':d': d_name}
                )

                # tell IoT core
                payload = {
                    'command': 'reserve',
                    'spot_id': best_id,
                    'license_plate': lp,
                    'travel_time': sim_time
                }
                iot.publish(topic='parking/cmd', qos=1, payload=json.dumps(payload))

        elif sid != 'GATE':
            # regular spot status update
            print(f"Update for {sid}: {status}")
            
            if status == 'free':
                # clear it
                tbl_spots.update_item(
                    Key={'spot_id': sid},
                    UpdateExpression="set #s=:s, #l=:l, #d=:d",
                    ExpressionAttributeNames={'#s': 'status', '#l': 'license_plate', '#d': 'driver'},
                    ExpressionAttributeValues={':s': 'free', ':l': 'None', ':d': 'None'}
                )
            elif status == 'occupied':
                # someone parked
                who = "Guest"
                try:
                    r = tbl_users.get_item(Key={'license_plate': lp})
                    if 'Item' in r:
                        who = r['Item']['name']
                except:
                    pass
                
                tbl_spots.update_item(
                    Key={'spot_id': sid},
                    UpdateExpression="set #s=:s, #l=:l, #d=:d",
                    ExpressionAttributeNames={'#s': 'status', '#l': 'license_plate', '#d': 'driver'},
                    ExpressionAttributeValues={':s': 'occupied', ':l': lp, ':d': who}
                )

    except Exception as e:
        print("CRITICAL LOGIC ERROR:", e)

    # always update the web view at the end
    refresh_s3_json()
    return {'statusCode': 200}