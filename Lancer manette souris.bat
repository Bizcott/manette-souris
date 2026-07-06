@echo off
rem Lance sans fenetre de console ; l'application vit dans la zone de
rem notification (tray). Pour du debug, lancer : python manette_souris.py
start "" pythonw -X utf8 "%~dp0manette_souris.py"
