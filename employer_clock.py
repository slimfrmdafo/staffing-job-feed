"""Independent employer hourly relay using the verified server-side timer pattern."""
import os
import cloud_clock

def employer_call(method,path,payload=None):
    return cloud_clock.api(method,path.replace('clock.yml','employer-clock.yml').replace('collect.yml','employer-collect.yml'),payload)
if __name__=='__main__':cloud_clock.tick(call=employer_call)
