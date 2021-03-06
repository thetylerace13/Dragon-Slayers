
from Missions.mission import Mission
import random
import math




class YStrafingTargetMission(Mission):

    def __init__(self):
        self.direction = 1

   
    
    def chat_command_init(self,shoot_agent, move_agent, params):
      shoot_agent.commands.append((shoot_agent, "chat /kill @e[type=!player]", 0))
      shoot_agent.commands.append((shoot_agent, "hotbar.1 1", 0))
      shoot_agent.commands.append((shoot_agent, "hotbar.1 0", 0))
      move_agent.commands.append((move_agent, "chat /gamemode 3", 0))
      move_agent.commands.append((move_agent, "jump 1", 0))
      move_agent.commands.append((move_agent, "jump 0", params[2]))
      move_agent.commands.append((move_agent, "chat /gamemode 1", params[2]))



    

    def ai_toggle(self, move_agent):
        self.direction *= -1
        if self.direction == 1:
            move_agent.agent.sendCommand("crouch 0")
            move_agent.agent.sendCommand("jump 1")
        else:
            move_agent.agent.sendCommand("crouch 1")
            move_agent.agent.sendCommand("jump 0")
