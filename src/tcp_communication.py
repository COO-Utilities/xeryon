""" TCP version of the Xeryon communication class """
import socket
import threading
import time
from Xeryon_HISPEC import outputConsole

class Communication:
    """ TCP version of the Xeryon communication class """
    readyToSend = None  # List that contains commands that are ready to send.
    stop_thread = False  # Boolean for stopping the thread.
    thread = None
    xeryon_object = None  # Link to the "Xeryon" object.

    def __init__(self, xeryon_object, tcp_address = "127.0.0.1", tcp_port = 10001):
        self.xeryon_object = xeryon_object
        self.tcp_address = tcp_address
        self.tcp_port = tcp_port
        self.readyToSend = []
        self.thread = None
        self.socket = None
        pass

    def start(self, external_communication_thread = False):
        """
        :return: None
        This starts the tcp communication on the specified ip address and port in a seperate thread.
        """
        if self.tcp_address is None:
            raise Exception("No COM_port could automatically be found. You should provide it manually.")
        

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.tcp_address, self.tcp_port))
            if external_communication_thread is False:
                self.stop_thread = False
                self.thread = threading.Thread(target=self.__processData)
                self.thread.daemon = True
                self.thread.start()
            else:
                return self.__processData
        except Exception as e:
            outputConsole("An error occured while trying to connect to: " + self.tcp_address + ":" + self.tcp_port, True, True)
            outputConsole(str(e), True, True)
            raise Exception("Could not conect to: " + self.tcp_address + ":" + self.tcp_port)
        

    def sendCommand(self, command):
        """
        :param command: The command that needs to be send.
        :return: None
        This function adds the command to the readyToSend list.
        """
        self.readyToSend.append(command)

    def setCOMPort(self, com_port):
        raise NotImplementedError()


    def __processData(self, external_while_loop = False):
        """
        :return: None
        This function is ran in a seperate thread.
        It continously listens for:
        1. If there is data to send
            Than it just writes the command.
            It strips all the new lines from the command and adds it's own.
        2. If there is data to read
            It reads the data line per line and checks if it contains "=".
            It determines the correct axis and passes that data to that axis class.
        3. Thread stop command.
        """
        try:
            while self.stop_thread is False and self.socket is not None:  # Infinite loop

                # SEND 10 LINES, then go further to reading.
                dataToSend = list(self.readyToSend[0:10])
                self.readyToSend = self.readyToSend[10:]

                for command in dataToSend:  # Send commands.
                    self.socket.sendall(str.encode(command.rstrip("\n\r") + "\n"))

                max_to_read = 10
                try:
                    socket_file = self.socket.makefile()
                    while max_to_read > 0:  # While there is data to read
                        reading = socket_file.readline()
                        if not reading:
                            break
                
                        if "=" in reading:  # Line contains a command.

                            if len(reading.split(":")) == 2: #check if an axis is specified
                                axis = self.xeryon_object.getAxis(reading.split(":")[0])
                                reading = reading.split(":")[1]
                                if axis is None:
                                    axis = self.xeryon_object.axis_list[0]
                                axis.receiveData(reading)

                            else:
                                # It's a single axis system
                                axis = self.xeryon_object.axis_list[0]
                                axis.receiveData(reading)

                        max_to_read -= 1
                except Exception as e:
                    print(str(e))

                if external_while_loop is True:
                    return None

                # NOTE: (HISPEC MOD) added a delay here so that we don't use as much CPU power on this loop
                time.sleep(0.01)

            # Close the tcp communication here, so we have a clean exit.     
            self.socket.close()
            print("Communication has stopped. ")
        except Exception as e:
            print("An error has occured that crashed the communication thread.")
            print(str(e))
            raise OSError("An error has occurred that crashed the communicaiton thread. \n" + str(e))
  

    def closeCommunication(self):
        self.stop_thread = True
