from win32com.client import Dispatch

s = Dispatch("SAPI.SpVoice")
s.Speak("Hello World")