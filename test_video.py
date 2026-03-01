import os, time
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["SDL_VIDEO_KMSDRM_DEVICE"] = "/dev/dri/card0"

import pygame
pygame.init()

screen = pygame.display.set_mode((640, 480))  # your screen size
screen.fill((255, 0, 0))
pygame.display.flip()

print("If you see RED for 5 seconds, video is working.")
time.sleep(5)
