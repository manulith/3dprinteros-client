import utils
utils.init_path_to_libs()
import numpy as np
import cv2
import time

cameras_names = {}
cap = {}
cc = 0

while(True):
    cap[cc] = cv2.VideoCapture(cc)
    is_opened = cap[cc].isOpened()
    cap[cc].release()
    if not is_opened:
        print("braking")
        break
    cameras_names[cc] = 'Camera ' + str(cc)
    print(cameras_names[cc])
    cc += 1

frame = {}

print("Cameras detected: " + str(cc))

while(True):
    for cam_num in range(0, cc):
        cap[cam_num] = cv2.VideoCapture(cam_num)
        cap[cam_num].set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 320)
        cap[cam_num].set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 240)
        frame_number = 0
        while(frame_number<50):
            ret, frame[cam_num] = cap[cam_num].read()
            # sharpen
            # blur = cv2.GaussianBlur(frame[cam_num],(0,0),3)
            # frame2 = cv2.addWeighted(frame[cam_num],1.5,blur,-0.5,0)  # 0.7,blurr,0.3,0) cv::addWeighted(frame, 1.5, image, -0.5, 0, image);
            cv2.imshow('frame'+str(cam_num),frame2)
            frame_number += 1
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        cap[cam_num].release()
cv2.destroyAllWindows()