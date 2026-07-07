Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "d:\ClothesNetData\chat-platform"
WshShell.Run "C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe server.py --port 8765", 0, False
WScript.Sleep 1000
