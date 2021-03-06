#!/usr/bin/env python

import numpy as np

import matplotlib.pyplot as plt
import rospy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import MapMetaData
from nav_msgs.msg import OccupancyGrid
from nav_msgs.msg import Odometry
from nav_msgs.msg import Path
import time
import matplotlib.pyplot as plt
import std_msgs.msg
from std_msgs.msg import String
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped
from math import cos, sin, atan2, fabs, sqrt
import numpy as np
import heapq

rospy.init_node('path_planner_node', anonymous=True)
rate = rospy.Rate(1)

class Node():
    def __init__(self, parent = None, state = None, movement = (0,0)):
        self.parent = parent        # previous state
        self.x = state[0]           # x position
        self.y = state[1]           # y position
        self.theta = 0              # orientation

        self.movement = (movement[0], movement[1]) # movement from previous to this state
        
        self.g = 0 # path length cost
        self.h = 0 # euclidian distance to target cost
        self.w = 0
        self.f = 0 # combined cost

    def __eq__(self, other):
        if type(other) is type(self):
            return (self.x == other.x and self.y == other.y)
        else:
            return False
        

    def __lt__(self, other):
        if type(other) is type(self):
            return self.f < other.f
        else:
            return self.g < other

class PathPlanner():
    def __init__(self):
        # map settings
        self.map = []
        self.map_width = 0
        self.map_height = 0
        self.map_resolution = 0
        self.map_minx = 0
        self.map_miny = 0

        # odometry and grid position
        self.x_start_odom = 0 # [m]
        self.y_start_odom = 0 # [m]
        self.x_start_grid = 0 # [1]
        self.y_start_grid = 0 # [1]

        # target position
        self.x_target_odom = 0 # [m]
        self.y_target_odom = 0 # [m]
        self.x_target_grid = 0 # [1]
        self.y_target_grid = 0 # [1]

        # time variables
        self.time_start = time.time()
        self.TIME_LIMIT = 200

        if rospy.get_param("/round") == 2:
            print("round 2: allow longer time")
            self.TIME_LIMIT = 500


        self.motion_short = [(-1, 0), (0, 1), (1, 0), (0, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)]

    def Main(self):
        while not rospy.is_shutdown():
            rate.sleep()

    def mapCallback(self, msg):
        self.map_width = msg.info.width
        self.map_height = msg.info.height
        self.map = msg.data
        self.map_resolution = msg.info.resolution
        self.map_minx = msg.info.origin.position.x
        self.map_miny = msg.info.origin.position.y

    def filterCallback(self, msg):
        # current position as starting position   
        self.x_start_odom = msg.pose.pose.position.x
        self.y_start_odom = msg.pose.pose.position.y
        self.x_start_grid = (int)((self.x_start_odom - self.map_minx)/self.map_resolution)
        self.y_start_grid = (int)((self.y_start_odom - self.map_miny)/self.map_resolution)

    def new_start(self, point):
        # manual starting position
        self.x_start_odom = point[0]
        self.y_start_odom = point[1]
        self.x_start_grid = (int)((self.x_start_odom - self.map_minx)/self.map_resolution)
        self.y_start_grid = (int)((self.y_start_odom - self.map_miny)/self.map_resolution) 

    def new_target(self, point):
        self.x_target_odom = point[0]
        self.y_target_odom = point[1]
        self.x_target_grid = (int)((self.x_target_odom - self.map_minx)/self.map_resolution) 
        self.y_target_grid = (int)((self.y_target_odom - self.map_miny)/self.map_resolution)

    def is_in_bounds(self, x, y):
        if (x >= 0 and x < self.map_width):
            if (y >= 0 and y < self.map_height):
                return True
        return False

    def obstacle_collision(self, x, y):
        status = False
        if self.is_in_bounds(x, y):
            status = (self.map[x + y*self.map_width] == 100) or (self.map[x + y*self.map_width] == -2)
        return status

    def inflate_collision(self, x, y):
        status = False
        status = (self.map[x + y*self.map_width] == 100) or (self.map[x + y*self.map_width] == -2) or (self.map[x + y*self.map_width] == -20)
        return status

    def update_target(self, msg):
        print("new target aquired")
        point = (msg.pose.position.x, msg.pose.position.y)
        self.new_target(point)

        # check if start and target is within map
        if not self.is_in_bounds(self.x_start_grid, self.y_start_grid):
            print("ROBOT POSITION OUTSIDE MAP")
            flag = "NO_PATH_FOUND"
            self.send_flag(flag) 
            return
            
        # check if target is within map
        if not self.is_in_bounds(self.x_target_grid, self.y_target_grid):
            print("TARGET POSITION OUTSIDE MAP")
            flag = "NO_PATH_FOUND"
            self.send_flag(flag)   
            return

        self.execute_planner()

    def euclidian_dist(self, x, y, xt, yt):
        h = np.sqrt((x - xt)**2 + (y - yt)**2) 
        return h

    def position_penalty(self, x, y, move_cost):
        w = 0
        if self.map[x + y*self.map_width] == -2:
            w = 2.5*move_cost
        elif self.map[x + y*self.map_width] == -20:
            w = 1.7*move_cost
        elif (self.map[x + y*self.map_width] == -40):
            w = 1.2*move_cost
        return w

    def get_closest_free_space(self, x0, y0):
        print("getting new grid cell")
        free_cell = False
        r = 1
        while not free_cell:
            for motion in [(-r, 0), (0, r), (r, 0), (0, -r), (-r, r), (r, r), (r, -r), (-r, -r)]:
                if self.obstacle_collision(x0 + motion[0], y0 + motion[1]):
                    continue
                else:
                    print("grid cell fix DONE")
                    return (x0 + motion[0], y0 + motion[1])
            r = r + 1

    def execute_planner(self):
        # time stamp
        self.time_start = time.time()

        path, visited = self.A_star()

        if len(path) > 0:
            print("starting cell:", self.x_start_grid, self.y_start_grid)
            path_smooth = self.smooth_path(path)
            print("goal cell:", self.x_target_grid, self.y_target_grid)

            # construct the path to be published to the path follower
            rviz_path = Path()
            rviz_path.header.frame_id = 'map' 

            #'''
            for c in path_smooth:
                path_x = c[0]
                path_y = c[1]
                pose = PoseStamped()
                #pose.header.frame_id = 'map' 
                pose.pose.position.x = path_x
                pose.pose.position.y = path_y
                rviz_path.poses.append(pose)
                #plt.plot(path_x, path_y, ".r", label="course")                  
            #'''
            #plt.grid(True)
            #plt.axis("equal")
            #plt.show()
            path_pub.publish(rviz_path)

    def send_flag(self, flag_message):
        flag = std_msgs.msg.String()
        flag.data = flag_message
        flag_pub.publish(flag)

    #########################################
    #                   A*                  #
    #########################################
    def A_star(self):
        print("A* algorithm started")
        # environment bounds [m]
        xlb = 0
        xub = self.map_width
        ylb = 0
        yub = self.map_height

        # inital position [m]
        x0 = self.x_start_grid
        y0 = self.y_start_grid
        
        # if starting position not in free space, adjust the starting node
        if self.obstacle_collision(x0, y0):
            x0, y0 = self.get_closest_free_space(x0, y0)
        
        # target coordinates [m]
        xt = self.x_target_grid
        yt = self.y_target_grid

        # if goal position not in free space, adjust the goal node
        #if self.obstacle_collision(xt, yt):
        #    xt, yt = self.get_closest_free_space(xt, yt)

        # initialize start and end node
        start_node = Node(None, (x0, y0))
        end_node = Node(None, (xt, yt))

        # initialize open and closed list
        alive_list = []
        dead_list = []

        # append the start node to the open list
        heapq.heappush(alive_list, start_node)

        visited = []
        iter = 0
        # run algorithm until the end node (target state) is found
        while len(alive_list) > 0:
            iter = iter + 1              
            elapsed = time.time() - self.time_start       
    
            # get the best node with lowest total cost (first item in list)
            current_node = alive_list[0]

            # store the current path
            visited.append((current_node.x, current_node.y))

            # remove the current node from the open list, and add it to the closed list
            heapq.heappop(alive_list)
            dead_list.append(current_node)

            # check if the current node is on the goal
            if current_node == end_node:        
                path = []
                current = current_node
                while current is not None:
                    path.append((current.x, current.y))         # append the path
                    current = current.parent

                print("iters:", iter)
                return path[::-1], visited[::-1]                # retrun the path (in reversed order)

            elif elapsed > self.TIME_LIMIT:
                print("NO PATH FOUND!")
                flag = "NO_PATH_FOUND"
                self.send_flag(flag)
                return [], []
            

            # generate new children (apply actions to the current best node)
            children = []
            for motion in self.motion_short:
                # get the new node state
                node_state = (current_node.x + motion[0], current_node.y + motion[1]) # simulate the motion

                # check that the position is within the bounds
                if node_state[0] > xub or node_state[0] < xlb or node_state[1] > yub or node_state[1] < ylb:
                    continue

                # check that the position is not on obstacle
                #print(node_state[0], node_state[1], end_node.x, end_node.y)
                if self.euclidian_dist(node_state[0], node_state[1], end_node.x, end_node.y) < 5: 
                    pass
                    #print("close to goal, let planner go into yellow area")
                else:
                    if self.obstacle_collision(node_state[0], node_state[1]):
                        continue

                # if the criteria above are fulfilled, create and append the node
                new_node = Node(current_node, node_state, motion)
                children.append(new_node)

            # loop through the children and compare with already alive and dead nodes
            for child in children:
                
                # check if child is on the closed list
                if child in dead_list:
                    continue 

                if child in alive_list: 
                    continue
                    
                # generate the f, g, h metrics
                move_cost = np.sqrt(child.movement[0]**2 + child.movement[1]**2)
                child.g = current_node.g + move_cost*0.40                                        # path length penalty
                child.w = current_node.w + self.position_penalty(child.x, child.y, move_cost)   # position penalty
                child.h = self.euclidian_dist(child.x, child.y, end_node.x, end_node.y)         # euclidian distance
                child.f = child.g + child.h + child.w                                           # total cost

                # check if child is already in the open list and compare cost
                if child in alive_list: 
                    continue
                    #if child.g >= max(alive_list).g:
                    #    continue          
                    if child.g >= alive_list[alive_list.index(child)].g:                      
                        continue

                # if the child is neither in the closed list nor open list, add it to the open list
                heapq.heappush(alive_list, child)

        # if no path found
        print("NO PATH FOUND!")
        flag = "NO_PATH_FOUND"
        self.send_flag(flag)      
        return [], []               # retrun the path (in reversed order)

    #########################################
    #              SMOOTHING                #
    #########################################

    def smooth_path(self, path):
        smooth_path = []
        path_x = []
        path_y = []
        last_ok = path[0] # last reached grid cell on the original path
        start = path[0] # start grid to search 

        ray_length = 3
        ray_iters = 0

        counter = 0
        idx = 1
        while True:
            counter = counter + 1
            if (idx >= len(path) - 1 or counter > len(path)*4):
                # exit the loop
                break

            # perform raytrace    
            free_path, collision = self.raytrace(start, path[idx])         

            if not collision:  
                ray_iters = ray_iters + 1    
                # last reached grid cell (without collision)
                last_ok = path[idx]
                ray_length = 3*len(free_path)
                idx = idx + 1

                if (idx >= len(path) - 1 or counter > len(path)*4):
                    # add the last bit of the ray trace
                    path_x = np.linspace(start[0]*self.map_resolution + self.map_minx, last_ok[0]*self.map_resolution + self.map_minx, num=ray_length, endpoint=True)
                    path_y = np.linspace(start[1]*self.map_resolution + self.map_miny, last_ok[1]*self.map_resolution + self.map_miny, num=ray_length, endpoint=True)
                    for i in range(ray_length):
                        smooth_path.append((path_x[i], path_y[i]))

            # if collision draw a straight line from the current start to the last_ok grid cell
            else:           
                if ray_iters == 0:  
                    ray_length = 5               
                    path_x = np.linspace(start[0]*self.map_resolution + self.map_minx, path[idx][0]*self.map_resolution + self.map_minx, num=ray_length, endpoint=True)
                    path_y = np.linspace(start[1]*self.map_resolution + self.map_miny, path[idx][1]*self.map_resolution + self.map_miny, num=ray_length, endpoint=True)
                    # update ray start to the last grid cell
                    start = path[idx]
                    #idx = idx + len(free_path)
                    idx = idx + ray_iters + 1

                elif ray_iters > 0:     
                    path_x = np.linspace(start[0]*self.map_resolution + self.map_minx, last_ok[0]*self.map_resolution + self.map_minx, num=ray_length, endpoint=True)
                    path_y = np.linspace(start[1]*self.map_resolution + self.map_miny, last_ok[1]*self.map_resolution + self.map_miny, num=ray_length, endpoint=True)
                    # update ray start to the last_ok grid cell
                    start = last_ok

                # append the straight line
                for i in range(ray_length):
                    smooth_path.append((path_x[i], path_y[i]))

                ray_iters = 0
        

        # smooth the path with a averaging window
        n_window = 18
        smooth_path_final = smooth_path

        for i in range(n_window/2+1, len(smooth_path) - n_window - 1):
            sumx = 0
            sumy = 0
            for j in range(-n_window/2,n_window/2):
                sumx = sumx + smooth_path[i+j][0]
                sumy = sumy + smooth_path[i+j][1]
            smooth_path_final[i] = (sumx/n_window, sumy/n_window)
     
        print("LEN", len(smooth_path_final))
        return smooth_path_final

    def raytrace(self, start, end):
        (start_x, start_y) = start
        (end_x, end_y) = end
        x = start_x
        y = start_y
        (dx, dy) = (fabs(end_x - start_x), fabs(end_y - start_y))
        n = dx + dy
        x_inc = 1
        if end_x <= start_x:
            x_inc = -1
        y_inc = 1
        if end_y <= start_y:
            y_inc = -1
        error = dx - dy
        dx *= 2
        dy *= 2

        traversed = []
        for i in range(0, int(n)):      
            if self.inflate_collision(int(x), int(y)):# and self.euclidian_dist(int(x), int(y), self.x_target_grid, self.y_target_grid) >= 2:
                return traversed, True
            traversed.append((int(x), int(y)))

            if error > 0:
                x += x_inc
                error -= dy
            else:
                if error == 0:
                    if self.inflate_collision(int(x + x_inc), int(y)):# and self.euclidian_dist(int(x), int(y), self.x_target_grid, self.y_target_grid) >= 2:
                        return traversed, True
                    traversed.append((int(x + x_inc), int(y)))
                y += y_inc
                error += dx

        return traversed, False


if __name__ == '__main__':
    print("path planner node started")

    pp = PathPlanner()
    rospy.Subscriber('/move_base_simple/goal', PoseStamped, pp.update_target)
    rospy.Subscriber("/maze_map_node/map", OccupancyGrid, pp.mapCallback)
    rospy.Subscriber("/robot_filter", Odometry, pp.filterCallback)
    path_pub = rospy.Publisher('/aPath', Path, queue_size=10)
    flag_pub = rospy.Publisher('/flag_pathplanner', std_msgs.msg.String, queue_size=1)
    pp.Main()
    



