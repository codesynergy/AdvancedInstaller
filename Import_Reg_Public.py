#!/usr/bin/env python

#Import_Reg.py
#Python 3.X
#By codesynergy
#Last Updated: June 2, 2015
#This script imports a registry file into a given component in an Advanced Installer project file.
#Arguments: 
	#RegistryFile.reg - The registry file you want to import. Must be in UTF-8 w/o BOM format.
	#AdvancedInstallerProjectFile.aip - The AI project file you want to import the registry file into.
	#ComponentName - the component that you want to attach the registry entries to. This is case sensitive. The component name must exist in the project file.
	#ComProperty - true or false - add "[COM_PROP1]" to the registry entries, so you can have duplicates (in the case of 64bit and 32bit components that have the same registry entries)	
					#AI adds "[COM_PROP1]", a property that resolves to an empty string, to a registry entry that already exists. This allows the duplicate to also show up in the AI UI (in the "COM" view)
					#I don't believe this property is required for the actual build of the installer. So, if you don't care how the registry entries show up inside of AI, just leave this argument as "false".
	#Platform - 32 or 64 - are these registry entries being made in the 32bit or 64bit registry hive.
	#ComponentInstallDir - the installation directory MSI property that the component is being installed to. Ex: "[APPDIR]"
#Example: Import_Reg.py MyFile.reg MyAIProject.aip MyFileComponent false 32 [APPDIR] >C:\out.txt	
#A batch file example: %ImportRegFile% "%RegFileDir%MyProgram.reg" %AIProjectFile% MyProgram.dll %COMProperty% %Bitness% [APPDIR]
#Notes:
#Currently, the reg file must be in the following format:UTF-8 w/o BOM, which is not the default reg file encoding.
#Other than the encoding, registry files need to be in the format as if they were "exported" from the windows registry.
#AI formats the values of a key in a specific way (character escapes, [APPDIR], etc.). It is likely that I did not address every formatting scenario.
#The "FormatAIRegEntry" function can be modified to address further formatting issues.
#Also, window's registry entries are formatted in a certain way. It's possible I did not address every formatting scenario, especially foreign characters.
#This script should not be run on the same AI project file more than once, as it will just keep appending registry entries. So, either run this script on your project file once, and check in the changes. Or, run the script on your AI project file during the build process, but don't save the registry additions.


import sys
import os
import re
import xml.etree.ElementTree as ET
import fileinput
import binascii
import base64


#First command line argument is the registry file that we want to import into the AI project file.
strRegFilePath = sys.argv[1]
if(os.path.exists(strRegFilePath) == False):
	print ('Failed to find registry file', '\"'+strRegFilePath+'\".')
	sys.exit()
	
#Second command line argument is the AI project file.
strProjectFile = sys.argv[2]
if(os.path.exists(strProjectFile) == False):
	print ('Failed to find AI project file', '\"'+strProjectFile+'\".')
	sys.exit()	

#Third command line argument is the component you wish to import all the registry entries into.
strComponentName = sys.argv[3]
if(strComponentName == ""):
	print ('You must enter a component name')
	sys.exit()		
	
#Fourth command line argument is whether you want to add [COM_PROP1] to the registry entries. Must be 'true' or 'false'.
strComProperty = sys.argv[4]
if strComProperty == "true":
	strComProperty = True
elif strComProperty == "false":
	strComProperty = False
else:
	print ('ComProperty must be true or false.')
	sys.exit()	

#Fifth command line argument is whether the registry entries are being made to the 32bit or 64bit registry.
#Even though the component's "64-bit" flag determines which hive the entries are to be made,
#Some registry keys have values that need to be adjusted. For example \win32 vs \win64
strPlatform = sys.argv[5]
if(strPlatform != "64" and strPlatform != "32"):
	print ('You must enter a platform - 32 or 64.')
	sys.exit()		

#Installation directory of the component. Use the property name of the installation folder. 
#For most files, this will be "[APPDIR]". 
#However, some installations might install to folders outside of APPDIR. 
#For example, your program might install files to C:\MyFolder, which has the property name "[MYFOLDER]"
strComponentInstallDir = sys.argv[6]
if(strComponentInstallDir == ""):
	print ('You must enter a the installation directory property of the component. For most components, this will be "[APPDIR]"')	
	sys.exit()		
else:
	if(not strComponentInstallDir.startswith('[') or not strComponentInstallDir.endswith(']')):
		print ('Component installation directory is not in the correct format.')	
		print ('The installation directory should be in the format of an MSI property. For example, "[APPDIR]".')	
		sys.exit()


strIDPrefix = strComponentName + "_"

#Class representing the registry entry in Advanced installer.
class RegistryEntryAI:
	#I think AI uses this as the identifier (key) for the registry entry. 
	#AI seems to use the format <prefix>_<suffix>,
	#<prefix> is sometimes the type of registry entry (ex: AppID, ThreadingModel, etc); sometimes it is just an underscore
	#<suffix> is an increasing integer used to prevent duplicate identifier names.
	#For example, identifiers may look like: "AppID_1", "AppID_2", "Version_1", "Version_2", "__1", "__2", etc.
	#For now, we are going to use the component name as the prefix, and the suffix will start at 0, increasing by 1 for each new entry.
	strRegistry = strIDPrefix			
	strRoot = "0"						#What root registry hive the registry entry belongs to. Ex: HKEY_CLASSES_ROOT
	strKey = ""							#The registry key. Ex:CLSID\{12345678-1234-1234-1234-123456789ABC}\ProgID
	strName = ""						#Name of the value being created in the key. I think if the name is blank, the value is Default.
	strValue = ""						#The data the value contains.
	strComponent = ""					#Name of the component you want to attach the registry entries to. Must match the component name exactly. Case-sensitive	


def ParseRegistryFile(lstRegistryEntries):
	
	#Read registry file into a list. Easier to work with.
	regFileHandle = open(strRegFilePath)
	lstRegFile = []	
	for line in regFileHandle:
		lstRegFile.append(line)
	regFileHandle.close()	
	#To handle the very last registry entry correctly, our for loop below needs at least three \n characters.
	#To Do: handle this in the loop instead.
	lstRegFile.append("\n")
	lstRegFile.append("\n")
	lstRegFile.append("\n")
		
	#A registry entry block represents a key and all it's values in a registry file.
	lstRegistryEntriesBlocks = []
	
	#Let's clean the registry file and create a list of registry blocks.
	strRegistryBlock = ""
	bFoundParentKey = False		
	for line in lstRegFile:
		line = line.lstrip(" ")
		#Line is a key. 		
		pattern1 = re.compile("\[HKEY_.*\]")
		m1 = pattern1.match(line)
		
		#If you find a key, every line up to a newline should be part of the registry block.
		if (m1):
			bFoundParentKey = True
			strRegistryBlock = strRegistryBlock + line
			continue
		else:
			if (line == "\n"):
				if (strRegistryBlock != ""):				
					lstRegistryEntriesBlocks.append(strRegistryBlock)
				strRegistryBlock = ""
				bFoundParentKey = False
				continue
			
			if (bFoundParentKey == True):
				strRegistryBlock = strRegistryBlock + line			
			continue			
	
	#Some registry values are represented in multiple lines. In this case, the lines end with a "\".
	#Let's format our registry blocks so that these values are represented in a single line (remove the \n).
	#This makes the list of registry blocks easier to handle.
	#I'm using a separate for loop, because there may be more formatting required.
	for i, strRegistryBlock in enumerate(lstRegistryEntriesBlocks):
		if not strRegistryBlock:
			continue
		
		lstRegistryEntriesBlocks[i] = strRegistryBlock.replace("\\\n","")
	
	#Traverse through each line of a registry block and determine if it's a key or value.
	#Then, create a RegistryEntryAI object based on each registry entry.
	for strRegistryBlock in lstRegistryEntriesBlocks:
		if not strRegistryBlock:
			continue
			
		strRegistryBlock = strRegistryBlock.rstrip("\n")
		lstRegistryBlockLines = strRegistryBlock.split("\n")
									
		for strRegistryBlockLine in lstRegistryBlockLines:
				
			#Line is a key
			pattern1 = re.compile("\[HKEY_.*\]")
			m1 = pattern1.match(strRegistryBlockLine)
			
			#A key with no values.
			if (m1 and (len(lstRegistryBlockLines) == 1)):
				GenerateAIRegEntry("", strRegistryBlockLine, lstRegistryEntries)
				continue
			#A key with at least one value
			elif(m1 and (len(lstRegistryBlockLines) > 1)):
				continue
			
			GenerateAIRegEntry(strRegistryBlockLine, lstRegistryBlockLines[0], lstRegistryEntries)
	
	
#Create a new AI registry entry object containing the information about the registry entry read in from the file.
def GenerateAIRegEntry(strRegValue, strParentKey, lstRegistryEntries):

	CurrentRegistryEntry = RegistryEntryAI()	
		
	#Set registry identifier	
	global iIdentifierNumber
	iIdentifierNumber = iIdentifierNumber+1	
	
	CurrentRegistryEntry.strRegistry = GetRegistry(strParentKey, strRegValue)
	CurrentRegistryEntry.strRoot = GetRegRoot(strParentKey)
	CurrentRegistryEntry.strKey = GetRegKey(strParentKey)
	CurrentRegistryEntry.strName = GetRegName(strRegValue)
	CurrentRegistryEntry.strValue = GetRegValue(strRegValue)
	CurrentRegistryEntry.strComponent = strComponentName

	FormatAIRegEntry(CurrentRegistryEntry)
	
	lstRegistryEntries.append(CurrentRegistryEntry)

#For the registry entry objects we create, there is some special formatting for "strName" and "strValue".
def FormatAIRegEntry(CurrentRegistryEntry):
	
	#Paths need to be replaced by the installation directory of the component. 
	#EX: "C:\\Program Files\\MyCompany\\MyProduct\\program.exe"   >   "[APPDIR]program.exe".	
	replaceRegEx = strComponentInstallDir	
	CurrentRegistryEntry.strValue = re.sub(r"\w:(\\\\[\w~ ]+)+(\\\\|([\w ]+(?=\")))",replaceRegEx, CurrentRegistryEntry.strValue)
		
	if (strPlatform == "32"):
		CurrentRegistryEntry.strKey = CurrentRegistryEntry.strKey.replace("[PLATFORM]","win32")
	elif (strPlatform == "64"):
		CurrentRegistryEntry.strKey = CurrentRegistryEntry.strKey.replace("[PLATFORM]","win64")	
				
	
	#AI uses some different syntax to escape certain characters.
	#Order of replace needs to be taken into account.
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("&","&amp;")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("\\\"","&quot;")	
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("[","%temp1%")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("]","%temp2%")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("%temp1%","[\\[]")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("%temp2%","[\\]]")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("{","%temp1%")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("}","%temp2%")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("%temp1%","[\\{]")
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("%temp2%","[\\}]")
	#The properties representing the installation directory (ex: [APPDIR]) are a special case and the brackets are not escaped. 
	#Actually, any MSI property is a special case, and should not be escaped. 
	#But, how do we detect if it's an MSI property or not. 
	#For now, let's just handle the installation directory. Other properties can be hardcoded here.
	strComponentInstallDirTemp = strComponentInstallDir.strip('[]')
	CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("[\[]"+strComponentInstallDirTemp+"[\]]", "["+strComponentInstallDirTemp+"]")
	
	
	#AI formats Binary entries as follows:
	if (CurrentRegistryEntry.strValue.startswith("hex:")):
		strTemp = CurrentRegistryEntry.strValue.replace("hex:", "")
		strTemp = strTemp.replace(",", "")
		CurrentRegistryEntry.strValue = "#x" + strTemp
		
	#AI formats DWORD entries as follows:
	if (CurrentRegistryEntry.strValue.startswith("dword:")):
		strTemp = CurrentRegistryEntry.strValue.replace("dword:", "")
		i = int(strTemp, 16)
		CurrentRegistryEntry.strValue = "#" + str(i)	
		
	# #AI Converts Expandable String Value to:
	if (CurrentRegistryEntry.strValue.startswith("hex(2):")):
		strTemp = CurrentRegistryEntry.strValue.replace("hex(2):", "")		
		strTemp = strTemp.replace(",00", "")
		strTemp = strTemp.replace(",", "")
		CurrentRegistryEntry.strValue = "#%" + binascii.unhexlify(strTemp).decode('utf-8')
		
	# #AI Converts Multi String Value to:
	if (CurrentRegistryEntry.strValue.startswith("hex(7):")):
		strTemp = CurrentRegistryEntry.strValue.replace("hex(7):", "")
		#It looks like three double zeros in a row ("00,00,00") means a new line.
		#In AI, this is represented as "[~]"
		strTemp = strTemp.replace(",00,00,00", "0A")
		strTemp = strTemp.replace(",00", "")
		strTemp = strTemp.replace(",", "")
		
		CurrentRegistryEntry.strValue = binascii.unhexlify(strTemp).decode('utf-8')
		#AI represents new lines (in multi string values) as "[~]"
		CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("\n", "[~]")
	
	#If the name and the value are empty strings, then the entry is only a key.
	#If there is only a root key, and no values or child keys, it looks like AI sets the "Name" to a "+"
	#To Do: It's possible for a root key to be listed in the registry file with not values,
	#but the subsequent lines are child keys. So, we should not set the "Name" of the root key to "+".
	#For now, let's skip the child key check, as it shouldn't harm anything.
	if (CurrentRegistryEntry.strValue == "" and CurrentRegistryEntry.strName == ""):
		CurrentRegistryEntry.strName = "+"
			
	#Keys need to reflect the correct platform:
	if (strPlatform == "32"):
		CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("\win64]","\win32]")
	elif (strPlatform == "64"):
		CurrentRegistryEntry.strValue = CurrentRegistryEntry.strValue.replace("\win32]","\win64]")
		
	
def GetRegistry(strParentKey, strRegValue):	
	
	global iIdentifierNumber
	strRegistry = strIDPrefix + str(iIdentifierNumber)		
	
	return strRegistry
	
	
#Determine what registry hive the key belongs to, and assign the value that matches AI.
def GetRegRoot(strKey):	

	pattern = re.compile('HKEY_\w+_\w+')
	m = pattern.search(strKey)
	if m:
		if (m.group(0) == "HKEY_CLASSES_ROOT"):
			return 0
		if (m.group(0) == "HKEY_CURRENT_USER"):
			return 1
		if (m.group(0) == "HKEY_LOCAL_MACHINE"):
			return 2
		if (m.group(0) == "HKEY_USERS"):
			return 3
		if (m.group(0) == "HKEY_CURRENT_CONFIG"):
			return 5
	
	return 0

	
#Extract the key (everything that is not the root). 
#Ex:CLSID\{12345678-1234-1234-1234-123456789ABC}\ProgID in HKEY_CLASSES_ROOT\CLSID\{12345678-1234-1234-1234-123456789ABC}\ProgID
def GetRegKey(strKey):

	pattern = re.compile("\[HKEY_\w+_\w+\\\\")
	m = pattern.match(strKey)
	if m:
		strKeyTemp = re.sub(pattern, "", strKey, 0, 0)
		strKeyTemp = strKeyTemp[:-1]
	
		if strComProperty == True:
			iInsertPos = strKeyTemp.find("\\")
			if (iInsertPos != -1):
				strKeyTemp = strKeyTemp[:iInsertPos] + "[COM_PROP1]" + strKeyTemp[iInsertPos:]
			else:
				strKeyTemp = strKeyTemp + "[COM_PROP1]"
					
		return strKeyTemp
	
	return ""
	
	
#Get the name of the registry value. Ex: "AppID" in "AppID"="{00000000-0000-0000-0000-000000000000}"
def GetRegName(strRegValue):

	strNameTemp = ""
	
	#The current line is the Default value. 
	pattern = re.compile("@=\".*\"")
	m = pattern.match(strRegValue)
	if m:
		return ""
	
	#The current line is a non-default value 
	#pattern = re.compile("\".*\"=\".*\"")
	pattern = re.compile("\".*\"=.*")
	m = pattern.match(strRegValue)	
	if m:
		#extract the name of the registry value
		pattern2 = re.compile("\".*?\"")
		m2 = pattern2.findall(strRegValue)
		if m2:
			strNameTemp = m2[0].strip('"')	
	
	return strNameTemp


#Get the value of the registry value. Ex: "{00000000-0000-0000-0000-000000000000}" in "AppID"="{00000000-0000-0000-0000-000000000000}"
def GetRegValue(strRegValue):

	strValueTemp = ""
	
	#The current line is the Default value. 
	pattern = re.compile("@=\".*\"")
	m = pattern.match(strRegValue)
	if m:
		#extract the data for the value
		pattern2 = re.compile("\".*\"")
		m2 = pattern2.search(strRegValue)		
		if m2:
			strValueTemp = m2.group(0).strip('"')
	
	#The current line is a non-default value 
	#pattern = re.compile("\".*\"=\".*\"")
	pattern = re.compile("\".*\"=.*")
	#pattern = re.compile("\".*\"=([^\n\r]+)(\s+.*\r\n)*", re.MULTILINE)
	m = pattern.match(strRegValue)	
	if m:
		#extract the value of the registry value
		#pattern2 = re.compile("\".*?\"")
		pattern2 = re.compile("=.*")
		#pattern2 = re.compile("=.*", re.MULTILINE)
		m2 = pattern2.findall(strRegValue)
		if m2:			
			strValueTemp = m2[0].lstrip('=')
			strValueTemp = strValueTemp.strip('"')
	
	return strValueTemp
	
	
#Take the registry information we extracted and format it according to the AI XML.
#To do: use XML api for insertion
def FormatRegistryObjects(lstRegistryEntries, lstRegistryXMLEntries):

	#This string is the format of the AI XML for a registry entry.		
	strRegistryXMLEntry = "<ROW Registry=[%1] Root=[%2] Key=[%3][%4][%5] Component_=[%6]/>"
	
	for i in lstRegistryEntries:
		strRegistryXMLEntryTemp = strRegistryXMLEntry;
		strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%1]", "\""+i.strRegistry+"\"")
		strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%2]", "\""+str(i.strRoot)+"\"")
		strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%3]", "\""+i.strKey+"\"")
		#Handle the "Name" (there will not always be a "Name" entry)
		if(i.strName != "" ):
			strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%4]"," Name="+"\""+i.strName+"\"")
		else:
			strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%4]","")
		#Handle the "Value" (there will not always be a "Value" entry)
		if(i.strName != "+"):
			strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%5]"," Value="+"\""+i.strValue+"\"")
		else:
			strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%5]","")
		strRegistryXMLEntryTemp = strRegistryXMLEntryTemp.replace("[%6]", "\""+i.strComponent+"\"")	
			
		lstRegistryXMLEntries.append(strRegistryXMLEntryTemp)
		
	
#Insert registry XML into AI project file.
#To do: use XML api for insertion
def InsertRegistryEntries(lstRegistryXMLEntries):

	strRegComponent = ""
	for strLine in fileinput.input(strProjectFile, inplace=1):
		#We've found the XML element containing the registry entries.
		if "MsiRegsComponent" in strLine:	
			strRegComponent = True
		
		#We want to append our registry entries to the end of the MsiRegsComponent XML element.
		if ("</COMPONENT>" in strLine and strRegComponent == True):
			for i in lstRegistryXMLEntries:
				print ("    "+i)
			strRegComponent = False
				
		print (strLine, end="")

	
#Main{}

#List of RegistryEntryAI objects
lstRegistryEntries = []

#List of RegistryEntryAI objects formatted in AI's XML format (to be written to the AI project file)
lstRegistryXMLEntries = []

#The suffix that will be added to the 'registry' value in the RegistryEntryAI class (see the "RegistryEntryAI" class comments). 
#To Do: write a function to automatically detect the iIdentifierNumber based on the registry entries that already exist.
iIdentifierNumber = 0;

#Parse registry file and create RegistryEntryAI object that represent registry entries being inserted into the AI project.
ParseRegistryFile(lstRegistryEntries)

#Take the RegistryEntryAI objects we generated, and format them into XML formatted to AI's standards.
FormatRegistryObjects(lstRegistryEntries, lstRegistryXMLEntries)

#Print what will be inserted into the AI project file. 
#Uncomment this for debugging/troubleshooting.
# for i in lstRegistryXMLEntries:
	# print ("    " + i)

#Insert the XML into the AI project file.	
InsertRegistryEntries(lstRegistryXMLEntries)

#print ("Finished")
