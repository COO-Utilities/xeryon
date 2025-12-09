""" TCP enabled Xeryon controller """
import time
from Xeryon_HISPEC import outputConsole, Axis, SETTINGS_FILENAME
from tcp_communication import Communication


class TcpXeryon:
    """ TCP version Xeryon """
    axis_list = None  # A list storing all the axis in the system.
    axis_letter_list = None # A list storing all the axis_letters in the system.
    master_settings = None

    def __init__(self, tcp_address = "127.0.0.1", tcp_port = 10001):
        """
            :param tcp IP address: Specify the IP address
            :type tcp port: string
            :param baudrate: Specify the baudrate
            :type baudrate: int
            :return: Return a Xeryon object.

            Main Xeryon Drive Class, initialize with the COM port and baudrate for communication with the driver.
        """
        self.comm = Communication(self, tcp_address, tcp_port)  # Startup communication
        self.axis_list = []
        self.axis_letter_list = []
        self.master_settings = {}

    def isSingleAxisSystem(self):
        """
        :return: Returns True if it's a single axis system, False if its a multiple axis system.
        """
        return len(self.getAllAxis()) <= 1

    def start(self, external_communication_thread = False, external_settings_default = None, do_reset=True, send_settings=True):
        """
        :return: Nothing.
        This functions NEEDS to be ran before any commands are executed.
        This function starts the serial communication and configures the settings with the controller.


        NOTE: (HISPEC MOD) we added the do_reset flag so that we can disconnect and reconnect to the stage
                without doing a reset. This allows us to reconnect without having to re-reference the stage.
        NOTE: (HISPEC MOD) added the send_settings flag so we can dynamically disable file auto-sending
        """
        
        if len(self.getAllAxis()) <= 0:
            raise Exception(
                "Cannot start the system without stages. The stages don't have to be connnected, only initialized in the software.")
        
        comm = self.getCommunication().start(external_communication_thread)  # Start communication

        # (HISPEC MOD)
        if do_reset:
            for axis in self.getAllAxis():
                axis.reset()
            
            time.sleep(0.2)        

        self.readSettings(external_settings_default)  # Read settings file
        # (HISPEC MOD)
        if send_settings:
            self.sendMasterSettings()
            for axis in self.getAllAxis():  # Loop trough each axis:
                axis.sendSettings()  # Send the settings

        # Enable all axes
        for axis in self.getAllAxis():
            axis.sendCommand("ENBL=1")

        # ask for LLIM & HLIM value's
        # TODO: Put ECHO on temporarily so each questioned value is returned
        for axis in self.getAllAxis():
            axis.sendCommand("HLIM=?")
            axis.sendCommand("LLIM=?")
            axis.sendCommand("SSPD=?")
            axis.sendCommand("PTO2=?")
            axis.sendCommand("PTOL=?")
            if "XRTA" in str(axis.stage):
                axis.sendCommand("ENBL=3")
        
        
        if external_communication_thread:
            return comm
        

    def stop(self, isPrintEnd=True):
        """
        :return: None
        This function sends STOP to the controller and closes the communication.

        NOTE: (HISPEC MOD) we added the isPrintEnd flag to avoid unnecessary prints that may confuse users
        """
        for axis in self.getAllAxis():  # Send STOP to each axis.
            axis.sendCommand("ZERO=0")
            axis.sendCommand("STOP=0")
            axis.was_valid_DPOS = False
        self.getCommunication().closeCommunication()  # Close communication
        # (HISPEC MOD)
        if isPrintEnd:
            outputConsole("Program stopped running.")


    def stopMovements(self):
        """
        Just stop moving.
        """
        for axis in self.getAllAxis():
            axis.sendCommand("STOP=0")
            axis.was_valid_DPOS = False


    def reset(self, send_settings=True):
        """
        :return: None
        This function sends RESET to the controller, and resends all settings.

        NOTE: (HISPEC MOD) added the send_settings flag so we can dynamically disable file auto-sending
        """
        for axis in self.getAllAxis():
            axis.reset()
        time.sleep(0.2)

        self.readSettings()  # Read settings file again

        # (HISPEC MOD)
        if send_settings:
            for axis in self.getAllAxis():
                axis.sendSettings()  # Update settings

    def getAllAxis(self):
        """
        :return: A list containing all axis objects belonging to this controller.
        """
        return self.axis_list

    def addAxis(self, stage, axis_letter):
        """
        :param stage: Specify the type of stage that is connected.
        :type stage: Stage
        :return: Returns an Axis object
        """
        newAxis = Axis(self, axis_letter,
                       stage)
        self.axis_list.append(newAxis)  # Add axis to axis list.
        self.axis_letter_list.append(axis_letter)
        return newAxis

    # End User Commands
    def getCommunication(self):
        """
        :return: The communication class.
        """
        return self.comm

    def getAxis(self, letter):
        """
        :param letter: Specify the axis letter
        :return: Returns the correct axis object. Or None if the axis does not exist.
        """
        if self.axis_letter_list.count(letter) == 1:  # Axis letter found
            indx = self.axis_letter_list.index(letter)
            if len(self.getAllAxis()) > indx:
                return self.getAllAxis()[indx]  # Return axis
        return None

    def readSettings(self, external_settings_default = None):
        """
        :return: None
        This function reads the settings.txt file and processes each line.
        It first determines for what axis the setting is, then it reads the setting and saves it.
        If there are commands for axis that don't exist, it just ignores them.
        """
        try:
            if external_settings_default is None:
                file = open(SETTINGS_FILENAME, "r")
            else:
                file = open(external_settings_default, "r")

            for line in file.readlines():  # For each line:
                if "=" in line and line.find("%") != 0:  # Check if it's a command and not a comment or blank line.

                    line = line.strip("\n\r").replace(" ", "")  # Strip spaces and newlines.
                    axis = self.getAllAxis()[0]  # Default select the first axis.
                    if ":" in line:  # Check if axis is specified
                        axis = self.getAxis(line.split(":")[0])
                        if axis is None:  # Check if specified axis exists
                            continue  # No valid axis? ==> IGNORE and loop further.
                        line = line.split(":")[1]  # Strip "X:" from command
                    elif not self.isSingleAxisSystem():
                        # This line doesn't contain ":", so it doesn't specify an axis.
                        # BUT It's a multi-axis system ==> so these settings are for the master.
                        if "%" in line:  # Ignore comments
                            line = line.split("%")[0]
                        self.setMasterSetting(line.split("=")[0], line.split("=")[1], True)
                        continue

                    if "%" in line:  # Ignore comments
                        line = line.split("%")[0]

                    tag = line.split("=")[0]
                    value = line.split("=")[1]

                    axis.setSetting(tag, value, True, doNotSendThrough=True)  # Update settings for specified axis.

            file.close()  # Close file
        except FileNotFoundError as e:
            if external_settings_default is None:
                outputConsole("No settings_default.txt found.")
            else:
                raise e
            # self.stop()  # Make sure the thread also stops.
            # raise Exception(
                # "ERROR: settings_default.txt file not found. Place it in the same folder as Xeryon.py. \n "
                # "The settings_default.txt is delivered in the same folder as the Windows Interface. \n " + str(e))
        except Exception as e:
            raise e

    
    def setMasterSetting(self, tag, value, fromSettingsFile=False):
        """
            In multi-axis systems, commands without an axis specified are for the master.
            This function adds a setting (tag, value) to the list of settings for the master.
        """
        self.master_settings.update({tag: value})
        if not fromSettingsFile:
            self.comm.sendCommand(str(tag)+"="+str(value))
        if "COM" in tag:
            self.setCOMPort(str(value))
    
    
    def sendMasterSettings(self, axis=False):
        """
         In multi-axis systems, commands without an axis specified are for the master.
         This function sends the stored settings to the controller;
        """
        prefix = ""
        if axis is not False:
            prefix = str(self.getAllAxis()[0].getLetter()) + ":"

        for tag, value in self.master_settings.items():
            self.comm.sendCommand(str(prefix) + str(tag) + "="+str(value))

    def saveMasterSettings(self, axis=False):
        """
         In multi-axis systems, commands without an axis specified are for the master.
         This function saves the master settings on the controller.
        """
        if axis is None:
            self.comm.sendCommand("SAVE=0")
        else:
            self.comm.sendCommand(str(self.getAllAxis()[0].getLetter()) + ":SAVE=0")

    def setCOMPort(self, com_port):
        self.getCommunication().setCOMPort(com_port)


    def findCOMPort(self):
        """
        Not implemented
        :return:
        """
        raise NotImplementedError()
