$body = '{"title":"[Weekly Report] Please submit your weekly report","description":"Submit: 1)Work done 2)Results/Data 3)Issues 4)Next week plan","required_capabilities":["notification","data_quality"],"assigned_to":"BPT_Data_Check","priority":"high","creator":"Hermes"}'
Invoke-RestMethod -Uri "http://localhost:8765/api/tasks" -Method POST -Body $body -ContentType "application/json"
