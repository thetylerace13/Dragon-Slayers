try:
    from malmo import MalmoPython
except:
    import MalmoPython
import malmo.minecraftbootstrap

import os
import sys
import time
import json
import random
import math
import numpy as np
from matplotlib import pyplot as plt
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from timekeeper import TimeKeeper


def logistic(x):
    '''
    max_val / {1 + e^(-kx)}
    '''
    return 1/(1 + 2.71828**(-7*(x**1-0.5)))

def lerp(low, high, perc):
    return low + perc*(high-low)

def clamp(low, high, value):
    if value < low:
        return low
    if value > high:
        return high
    return value

def clamped_lerp(low, high, perc):
    return clamp(low, high, lerp(low, high, perc))



def load_grid(agent):
    wait_time = 0
    keeper = TimeKeeper()
    while wait_time < 10:
        #sys.stdout.write(".")
        world_state = agent.getWorldState()
        if not world_state.is_mission_running:
            return None
        if len(world_state.errors) > 0:
            raise AssertionError('Could not load grid.')

        if world_state.number_of_observations_since_last_state > 0 and \
           json.loads(world_state.observations[-1].text):
            result = json.loads(world_state.observations[-1].text)
            result["time"] = time.time()
            return result

        keeper.advance_by(0.05)
        wait_time += 0.05

def find_mob_by_name(mobs, name, new=False):
    for m in mobs:
        if m["name"] == name:
            return m
    return None
def find_entity_by_id(entities, id):
    for entity in entities:
        if entity["id"] == id:
            return entity

def find_new_arrow(entities, arrow_set):
    for entity in entities:
        if entity["name"] == "Arrow" and entity["id"] not in arrow_set:
            return entity

def magnitude(vector):
    return np.sqrt(np.sum(vector**2))

def flat_distance(vector):
    #magnitude of (x, 0, z).  Ignore y difference
    return math.sqrt(vector[0]**2 + vector[2]**2)

def vert_distance(xtarget, ztarget, xsource=0, zsource=0):
    return ((xtarget - xsource)**2 + (ztarget - zsource)**2) ** 0.5

def get_hori_angle(xorigin, zorigin, xtarget, ztarget):
    return math.degrees(math.atan2(xorigin-xtarget, ztarget-zorigin))

def get_angle_between(vector1, vector2):
    prod = np.dot(vector1, vector2)
    mag1 = np.sqrt(np.sum(vector1**2))
    mag2 = np.sqrt(np.sum(vector2**2))
    if mag1 == 0 or mag2 == 0:
        return 0
    return math.degrees(math.acos(max(-1, min(prod/(mag1*mag2), 1))))

def vector_from_angle(angle):
    return np.asarray([math.sin(math.radians(angle+180)), 0, math.cos(math.radians(angle))])

def project_vector(vector1, vector2):
    prod = np.dot(vector1, vector2)
    magsq = np.sum(vector2**2)
    return prod/magsq * vector2

def signed_quadratic_features(data, features, include_bias=False):
    result = np.zeros(data.shape)
    for i in range(len(data)):
        to_add = np.zeros(data.shape[1])
        square_indices = [int(j*features - j*(j-1)/2) for j in range(features)]
        to_add[:features] = data[i,:features]
        for j in range(features, data.shape[1]):
            if j-features in square_indices:
                ft = square_indices.index(j-features)
                if data[i,ft] < 0:
                    to_add[j] = -data[i,j]
                else:
                    to_add[j] = data[i,j]
            else:
                to_add[j] = data[i,j]
        result[i,:] = to_add
    return result

def get_closest_point(curve, target):
    '''
    Get closest points based on two lists of locations at times.
    Curve is a list of points that define a trajectory.
    Target is a list of points that define the target location.
    Returns the 2 closest points on the list of segments at a given time.
    ''' 

    if len(curve) == 0 or len(target) == 0:
        return None

    point1, point2 = curve[0][0], target[0][0]
    min_distance = magnitude(point1 - point2)
    for i in range(1, len(curve)):
        dist = magnitude(curve[i][0] - target[i][0])
        if dist < min_distance:
            point1, point2 = curve[i][0], target[i][0]
            min_distance = dist

    return point1, point2
def angle_clamp(angle):
    return ((angle + 180) % 360) - 180
AIMING = 0
SHOOT = 1
STATIC = 0
MOVING = 1
class ArrowTracker():

    def __init__(self, malmo_agent, arrow_id, target_id, stored_data, aim_data):
        self.malmo_agent = malmo_agent
        self.arrow_id = arrow_id
        self.target_id = target_id
        self.track_duration = 50
        self.delete_me = False
        self.target_data = []
        self.arrow_data = []
        self.stored_data = stored_data
        self.aim_data = aim_data
        self.count = 0

    def step(self, obs):
        target_transform = find_entity_by_id(obs["Mobs"],self.target_id)
        #Remove self if associated target does not exist
        if target_transform is None:
            self.delete_me = True
            return None
        if self.track_duration > 0:
            self.track_duration -= 1
            self.track_arrow(target_transform, obs)
        else:
            self.delete_me = True
            self.malmo_agent.analyze_arrow_trajectory(target_transform, self.arrow_data, self.target_data, self.stored_data, self.aim_data)

    def track_arrow(self,target_transform, obs):
        '''
        This function is run once per tick.
        Add the current position of the arrow to a list, if it is different from the
        previous position.
        '''
        arrow = find_entity_by_id(obs["Mobs"], self.arrow_id)
        #if arrow found
        if arrow:
            #get arrow location
            arrow_vec = np.asarray([arrow["x"], arrow["y"], arrow["z"]])
            #if first arrow data or different from previous arrow data
            #avoid appending duplicate adjacent data
            
            if len(self.arrow_data) == 0 or not np.array_equal(arrow_vec,self.arrow_data[-1][0]):
                self.target_data.append((np.asarray([target_transform["x"], target_transform["y"], target_transform["z"]]), obs["time"]))
                self.arrow_data.append((arrow_vec, obs["time"]))
        return None

  
class MalmoAgent():

    def __init__(self, name, agent, pitch, yaw, vert_step_size, hori_step_size, data_set):
        self.name = name
        self.agent = agent
        self.pitch = pitch
        self.yaw = yaw
        self._obs = None
        self.transform = None
        self.commands = []
        self.total_time = 0
        self.vert_step_size = vert_step_size
        self.hori_step_size = hori_step_size
        self.desired_pitch = pitch
        self.desired_yaw = yaw
        self.last_shot = 0
        #Data set encapsulates hori_shots and vert_shots
        self.data_set = data_set
        self.hori_errors = []
        self.vert_errors = []
        #Decide if we need to get data for vertical shots
        if self.data_set and not self.data_set.empty():
            vert_shots = np.asarray(self.data_set.vert_shots)[:,-1]
            max_angle = np.max(vert_shots)
            min_angle = np.min(vert_shots)
            self.vert_angle_step = 45 if max_angle - min_angle > 40 else 0
        else:
            self.vert_angle_step = 0
            
        #shooter parameters
        self.reset_shoot_loop()

        #train static shots for at least 12 shots
        #These do not reset between missions
        #self.hori_train_state = STATIC if len(self.data_set.hori_shots) < 500 else MOVING
        self.hori_train_state = MOVING
        self.vert_train_state = MOVING
        self.total_shots = 0
        self.total_hits = 0

    def reset_shoot_loop(self):
        self.min_aim_duration = 20
        self.max_record_duration = 120 #ticks
        self.shoot_state = AIMING
        self.aim_timer = 0
        self.shoot_timer = 0
        self.aim_on_target_ticks = 0
        self.end_mission = False
      
        self.listen_for_new_arrow = False
        self.arrow_ids = set()
        self.arrow_trackers = []
        self.aim_data = []
        self.stored_data = []
        self.current_data = []
        #Scales turning speed
        self.turn_speed_multiplier = (1/360)* 2   
        self.mission_shots = 0
        self.mission_hits = 0     

    def step(self, obs):
        #Run this once a tick
        if(obs is not None):
            self.set_obs(obs)
        self.total_time += 1
        self.process_commands(self.total_time)


    def shooter_step(self, shooter_obs, move_agent, target):
        '''
        This function:
        1. calls step()
        2. aims at targets
        3. shoots when aiming at target
        4. finds id of nearly fired arrows
        5. calls the step function of all arrow trackers
              -arrow trackers call record_data()
        6. returns whether a new shot has started
        '''
        result = False
        self.step(shooter_obs)
        #Abort if no target to aim at/record data for
        if target.transform is None:
            return None
        self.aim_data.append((angle_clamp(self.transform["yaw"]), -self.transform["pitch"], time.time()))
        mover_obs = move_agent._obs

        #aims over max_aim_duration many ticks
        if self.shoot_state == AIMING:
            if self.aim_timer < self.min_aim_duration:
                if self.aim_timer == 0:
                    #Calculate desired aim once at start of aiming loop
                    #aim_iteration is used to calculate rotation speed
                    self.agent.sendCommand("use 1")
                    result = True
                    self.desired_yaw, self.desired_pitch = self.calculate_desired_aim(target.transform)
                self.aim_timer += 1
                aiming_complete = self.aim_step(self.desired_yaw, self.desired_pitch)
                
            else:
                self.aim_timer = 0
                self.aim_on_target_ticks = 0
                self.shoot_state = SHOOT

        #Shoot if done aiming
        if self.shoot_state == SHOOT:
            self.agent.sendCommand("use 0")
            if self.shoot_timer < 2:
                self.shoot_timer += 1
            else:
                self.shoot_timer = 0
                self.shoot_state = AIMING
                self.listen_for_new_arrow = True
                self.vert_angle_step = min(45, self.vert_angle_step + 3)

        #Find newly fired arrows
        if self.listen_for_new_arrow:
            #An arrow has just been shot, so look through the observations and find it
            arrow = find_new_arrow(mover_obs["Mobs"],self.arrow_ids)
            if arrow != None:
                #add to set and stop listening for arrows
                self.arrow_ids.add(arrow["id"])
                self.arrow_trackers.append(ArrowTracker(self,arrow["id"], target.id, self.stored_data, self.aim_data))
                self.listen_for_new_arrow = False
                self.aim_data = []
                
        #Track positions of all arrows in flight
        self.track_arrows_step(mover_obs)
        return result


    def calculate_desired_aim(self, target_transform):
        distance = vert_distance(target_transform["x"], target_transform["z"], self.transform["x"], self.transform["z"])
        elevation = target_transform["y"] - self.transform["y"]
        obs_angle = ((get_hori_angle(self.transform["x"], self.transform["z"], target_transform["x"], target_transform["z"]) + 180) % 360) - 180
        rel_angle = ((obs_angle - self.transform["yaw"] + 180) % 360) - 180
        x_angle = ((obs_angle + 180 + 90) % 360) - 180
        x_velocity = project_vector(np.asarray([target_transform["motionX"], target_transform["motionY"], target_transform["motionZ"]]), vector_from_angle(x_angle))
        x_velocity = math.copysign(magnitude(x_velocity), math.cos(math.radians(get_angle_between(vector_from_angle(x_angle), x_velocity))))
        y_velocity = project_vector(np.asarray([target_transform["motionX"], target_transform["motionY"], target_transform["motionZ"]]), np.asarray([0, 1, 0]))
        y_velocity = math.copysign(magnitude(y_velocity), math.cos(math.radians(get_angle_between(np.asarray([0, 1, 0]), y_velocity))))
        z_velocity = project_vector(np.asarray([target_transform["motionX"], target_transform["motionY"], target_transform["motionZ"]]), vector_from_angle(obs_angle))
        z_velocity = math.copysign(magnitude(z_velocity), math.cos(math.radians(get_angle_between(vector_from_angle(obs_angle), z_velocity))))
        #set desired pitch
        delta_pitch = self.calculate_pitch(distance, elevation+1, y_velocity)
        #set desired yaw
        delta_yaw = self.calculate_yaw(rel_angle, distance, x_velocity, z_velocity)
        #Store some data points now to use for future data points
        self.stored_data = [x_velocity, y_velocity, z_velocity, angle_clamp(self.transform["yaw"])]
        return (((self.transform["yaw"] + delta_yaw + 180) % 360) - 180,-delta_pitch)

    def aim_step(self, desiredYaw, desiredPitch):
        '''
        Set pitch and yaw movement for a single tick.
        Returns true if aiming is complete
        '''
        if desiredYaw == None and desiredPitch == None:
            return
        
        #Get current yaw and pitch
        current_yaw = self.transform["yaw"]
        current_pitch = self.transform["pitch"]
        #Calculate difference in yaw and pitch to desired angle
        yaw_diff = 0
        if desiredYaw != None:
            yaw_diff = desiredYaw - current_yaw
        pitch_diff = 0
        if desiredPitch != None:
            pitch_diff = desiredPitch - current_pitch

        #If aiming at the right angle, return true
        allowable_deviation = 0 #degrees
        '''
        The curve from [0,1] is modified by exponentiating the value.
        This adjusts speeds when near 0 or near 1.
        '''
      
        if abs(yaw_diff) < allowable_deviation:
            self.agent.sendCommand("turn 0")
        else:
            #set aim direction
            yaw_multiplier = 1
            while yaw_diff > 180:
                yaw_diff = yaw_diff - 360
            while(yaw_diff < -180):
                yaw_diff = yaw_diff + 360
            yaw_multiplier = -1 if yaw_diff < 0 else 1
            self.agent.sendCommand("turn " + str(yaw_multiplier * abs(yaw_diff) * self.turn_speed_multiplier))

        if abs(pitch_diff) < allowable_deviation:
            self.agent.sendCommand("pitch 0")
        else:
            #set aim direction
            pitch_multiplier = -1 if pitch_diff < 0 else 1
            self.agent.sendCommand("pitch " + str( pitch_multiplier * abs(pitch_diff) * self.turn_speed_multiplier))



        
        if (abs(yaw_diff) < allowable_deviation and abs(pitch_diff) < allowable_deviation):
            #Aim is good when the aim has been on the target angle for two consecutive ticks.
            #This is to counteract times when aim is correct but current look velocity
            #is too high so it throws off the aim before the stop command is issued
            if self.aim_on_target_ticks >= 3:
                    return True   
            else:
                self.aim_on_target_ticks += 1
                return False

                
        
          
        #Aim not yet finished, return false and keep iterating
        self.aim_on_target_ticks = 0
        return False

    def track_arrows_step(self,mover_obs):
        #Iterate through arrow trackers
        for tracker in self.arrow_trackers:
            tracker.step(mover_obs)
        #Delete any completed trackers
        for i in reversed(range(len(self.arrow_trackers))):
            if self.arrow_trackers[i].delete_me:
                self.arrow_trackers.pop(i)

    def analyze_arrow_trajectory(self, target_transform, data, target_data, obs, aim_data): 
        #target_transform, self.arrow_data, self.target_data, self.stored_data, self.aim_data
        
        vert_error = 0
        hori_error = 0
        
        bounced_off = self.record_shot(target_transform,data,target_data,obs,aim_data)
        self.total_shots += 1
        self.mission_shots += 1
        if bounced_off:
            #record shot checks for arrows that bounce off
            self.total_hits += 1
            self.mission_hits += 1
        
        #Append errors depending on how close the arrow got
        #print(self.data_set.vert_shots[-1])
        closest_point, target_loc = get_closest_point(data, target_data)
        vert_error = closest_point[1] - target_loc[1]
        hori_error = magnitude(closest_point[::2] - target_loc[::2])

        self.vert_errors.append(vert_error)
        self.hori_errors.append(hori_error)
      

        return -((vert_error**2 + hori_error**2)**0.5)
    
    def record_shot(self, target_transform, arrow_data, target_data, obs, aim_data):
        #Record a shot against a static target
        #horizontal shot = [delta horizontal angle to target, yaw]
        if len(arrow_data) < 1:
            return 0
        #data_preds = []
        last_distance_from_player = 0
        current_distance_from_player = 0

        #Count the number of instances where distance to arrow decreases
        reverse_ticks = 0
        #unpack obs
        x_vel, y_vel, z_vel, player_yaw = obs
        pred_velocity = x_vel * vector_from_angle(((player_yaw + 180 + 90) % 360) - 180) + z_vel * vector_from_angle(player_yaw) + y_vel * np.asarray([0, 1, 0])
        player_loc = np.asarray([self.transform["x"], self.transform["y"], self.transform["z"]])

        for i in range(len(arrow_data)):
            #unpack arrow data
            arrow_loc = arrow_data[i][0]
            prev_arrow_loc = arrow_data[i-1][0]
            timestamp = arrow_data[i][1]
            if self.desired_pitch < 85 and (i == 0 or not np.array_equal(arrow_loc, prev_arrow_loc)):
                past_location = arrow_loc - pred_velocity*(timestamp-aim_data[0][2])
                ori_angle = angle_clamp(get_hori_angle(player_loc[0], player_loc[2], arrow_loc[0], arrow_loc[2]) - aim_data[0][0])
                pred_angle = angle_clamp(get_hori_angle(player_loc[0], player_loc[2], past_location[0], past_location[2]) - aim_data[0][0])
                ori_vert_angle = self.get_pitch_to_target(magnitude(arrow_loc[::2] - player_loc[::2]), arrow_loc[1] - player_loc[1])
                pred_vert_angle = self.get_pitch_to_target(magnitude(past_location[::2] - player_loc[::2]), past_location[1] - player_loc[1])
                past_angle = get_hori_angle(player_loc[0], player_loc[2], past_location[0], past_location[2])
                past_x_vel = project_vector(pred_velocity, vector_from_angle(angle_clamp(past_angle + 90)))
                past_x_vel = math.copysign(magnitude(past_x_vel), math.cos(math.radians(get_angle_between(vector_from_angle(angle_clamp(past_angle + 90)), past_x_vel))))
                past_z_vel = project_vector(pred_velocity, vector_from_angle(past_angle))
                past_z_vel = math.copysign(magnitude(past_z_vel), math.cos(math.radians(get_angle_between(vector_from_angle(past_angle), past_z_vel))))
                d_elevation = past_location[1] - player_loc[1]
                d_angle = angle_clamp(get_hori_angle(player_loc[0], player_loc[2], past_location[0], past_location[2]) - aim_data[0][0])
                #data_preds.append(pred_location)
                d_distance = magnitude(past_location[::2] - player_loc[::2])
                #get arrow position distance from shooter.  Ignore y-difference
                current_distance_from_player = flat_distance(arrow_loc-player_loc)

                #Arrow hits if arrow's distance from player decreases.  Arrow's should strictly move away from the player's shooting position if they do not hit anyone
                if i > 1 and current_distance_from_player < last_distance_from_player:
                    reverse_ticks += 1

                #Break if bounced off target
                if reverse_ticks >= 4:
                    self.data_set.vert_shots.pop(-1)
                    self.data_set.hori_shots.pop(-1)
                    if self.vert_train_state == MOVING:
                        self.data_set.vert_leading.pop(-1)
                        self.data_set.hori_leading.pop(-1)
                    break
                
                #Update previous position
                last_distance_from_player = current_distance_from_player

                self.data_set.vert_shots.append([d_distance, d_elevation, aim_data[-1][1]])
                if self.vert_train_state == MOVING:
                    self.data_set.vert_leading.append([d_distance, d_elevation, y_vel, ori_vert_angle - pred_vert_angle])
                
                if aim_data[-1][1] < 80 and aim_data[-1][1] > -45:
                    self.data_set.hori_shots.append([d_angle, angle_clamp(aim_data[-1][0] - aim_data[0][0])])
                    if self.hori_train_state == MOVING:
                        self.data_set.hori_leading.append([d_distance, past_x_vel, past_z_vel, angle_clamp(ori_angle - pred_angle)])

                #Update previous position
                last_distance_from_player = current_distance_from_player
        #An arrow hits the target if it has moved backward for more than 2 ticks
        return reverse_ticks >= 4

    def reset(self):
        #Reset the time for commands
        self.total_time = 0
        self.comands = []
        self._obs = None
        
    def set_obs(self, obs):
        if not obs:
            return
        self._obs = obs
        has_prev = self.transform is not None
        for entity in self._obs["Mobs"]:
            if entity["name"] == self.name:
                if has_prev:
                    # Append past data
                    self.transform["prevX"].append(self.transform["x"])
                    if len(self.transform["prevX"]) > 4:
                        self.transform["prevX"].pop(0)
                    self.transform["prevY"].append(self.transform["y"])
                    if len(self.transform["prevY"]) > 4:
                        self.transform["prevY"].pop(0)
                    self.transform["prevZ"].append(self.transform["z"])
                    if len(self.transform["prevZ"]) > 4:
                        self.transform["prevZ"].pop(0)
                    self.transform["prevTime"].append(self.transform["time"])
                    if len(self.transform["prevTime"]) > 4:
                        self.transform["prevTime"].pop(0)
                    
                else:
                    # Create past data if none exists
                    self.transform = {}
                    self.transform["prevX"] = []
                    self.transform["prevY"] = []
                    self.transform["prevZ"] = []
                    self.transform["prevTime"] = []

                # Apply stats not found in normal transforms
                old_transform = self.transform
                self.transform = entity
                self.transform["prevX"] = old_transform["prevX"]
                self.transform["prevY"] = old_transform["prevY"]
                self.transform["prevZ"] = old_transform["prevZ"]
                self.transform["prevTime"] = old_transform["prevTime"]
                self.transform["time"] = self._obs["time"]

                # Calculate velocity
                if has_prev:
                    self.transform["motionX"] = (self.transform["x"] - self.transform["prevX"][0]) / (self.transform["time"] - self.transform["prevTime"][0])
                    self.transform["motionY"] = (self.transform["y"] - self.transform["prevY"][0]) / (self.transform["time"] - self.transform["prevTime"][0])
                    self.transform["motionZ"] = (self.transform["z"] - self.transform["prevZ"][0]) / (self.transform["time"] - self.transform["prevTime"][0])


    def calculate_pitch(self, distance, elevation, y_velocity):
        #Return combined delta pitch to hit a target
        delta_pitch = self.get_pitch_to_target(distance, elevation)
        delta_pitch += self.get_leading_pitch(distance, elevation, y_velocity)
        return delta_pitch

    def get_pitch_to_target(self, distance, elevation):
        #returns pitch needed to aim at target at its current position
        array = np.asarray(self.data_set.vert_shots)
        if array.shape[0] > 100:
            if elevation > distance:
                filteredArray = array[array[:,-1] > 45]
            else:
                filteredArray = array[array[:,-1] <= 45]
            if filteredArray.shape[0] == 0:
                return self.vert_angle_step
            poly = PolynomialFeatures(3, include_bias=False).fit(filteredArray[:,:-1])
            model = LinearRegression().fit(poly.transform(filteredArray[:,:-1]), filteredArray[:,-1])
            return min(model.predict(poly.transform([[distance, elevation]]))[0], 89.9)

        return self.vert_angle_step

    def get_leading_pitch(self, distance, elevation, y_velocity):
        #adds extra pitch to compensate for moving targets
        array = np.asarray(self.data_set.vert_leading)
        if array.shape[0] > 100:
            poly = PolynomialFeatures(2, include_bias=False).fit(array[:,:-1])
            model = LinearRegression().fit(signed_quadratic_features(poly.transform(array[:,:-1]), 3), array[:,-1])
            return min(model.predict(signed_quadratic_features(poly.transform([[distance, elevation, y_velocity]]), 3))[0], 89.9)

        return 0
        
    def calculate_yaw(self, angle, distance, x_velocity, z_velocity):
        #self.hori_train_state = STATIC if len(self.data_set.hori_shots) < 500 else MOVING
        #Return combined delta yaw to hit a target
        delta_yaw = self.get_yaw_to_target(angle)
        delta_yaw += self.get_leading_yaw(distance,x_velocity,z_velocity)
        return delta_yaw

    def get_yaw_to_target(self, angle):
        #returns yaw needed to aim at target at its current position
        array = np.asarray(self.data_set.hori_shots)
        if array.shape[0] > 1000:
            poly = PolynomialFeatures(1, include_bias=False).fit(array[:,:-1])
            model = LinearRegression().fit(poly.transform(array[:,:-1]), array[:,-1])
            return min(max(-180, model.predict(poly.transform([[angle]]))[0]), 180)
        
        return random.randrange(-180, 180)

    def get_leading_yaw(self, distance, x_velocity, z_velocity):
        #adds extra yaw to compensate for moving targets
        array = np.asarray(self.data_set.hori_leading)
        if array.shape[0] > 100:
            poly = PolynomialFeatures(2, include_bias=False).fit(array[:,:-1])
            model = LinearRegression().fit(signed_quadratic_features(poly.transform(array[:,:-1]), 3), array[:,-1])
            return min(max(-180, model.predict(signed_quadratic_features(poly.transform([[distance, x_velocity, z_velocity]]), 3))[0]), 180)
        
        return 0

    def process_commands(self, mission_elapsed_time):
        for command in self.commands:
            if command[2] <= mission_elapsed_time:
                self.commands.remove(command)
                command[0].sendCommand(command[1])

