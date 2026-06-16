## Requirements
Rasberry pi 5
Rasberry pi sense-hat
Mouse
Keyboard
Monitor
Network connection


## Set up
The node first requires a network connection, this can be done thro Pi OS
After this you need to create a thingspeak account and create a channel. The channel needs to have 3 fields each with the defualt name given. Now collect the Channel_id from the channel settings tab.
From here setup a device and get the username, password and client_ID for this device.

On the resberry Pi the SenseHat and cyptography packages are required:
sudo apt install python3-cryptography
sudo apt install python3-sensehat

Next you need to download the entire EnvironmentNode Folder as it contains the encryption key (and testing credentials).

If it is first set up, a python virual environment needs to be created in-order to run the python script:
cd EnvironmentNode
python -m venv --system-site-packages venv

Next you must enter the python virtual environement using:
source venv/bin/activate

After this you are ready to run the script:
python EnvFinal.py

On start up you will be prompted to enter the credentials from thingspeak. These will be encrypted and saved locally so you do not have to repeat this step.
(There are already credentials within the file for testing)
Now Youre rasberry py should be sending data!

Finally update the API key within the api.js file:
For the environement node it is the top on under: THINGSPEAK_API_KEY

