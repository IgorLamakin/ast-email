; Дополнительные действия установщика для Windows.
;
; После обновления Explorer часто продолжает показывать старую иконку из
; своего кэша, даже если .exe уже содержит новую. Явно просим оболочку
; перечитать иконки и рассылаем SHCNE_ASSOCCHANGED.
!macro customInstall
  DetailPrint "Обновление кэша иконок Windows..."
  nsExec::ExecToLog '"$SYSDIR\ie4uinit.exe" -show'
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)'
!macroend
