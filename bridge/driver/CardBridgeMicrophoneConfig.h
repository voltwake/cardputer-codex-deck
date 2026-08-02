#pragma once

// Public input device. It deliberately has no output stream, matching the
// shape of a normal USB microphone in capture-device pickers.
#define kDriver_Name "CardBridge Microphone"
#define kPlugIn_BundleID "com.voltwake.cardbridge.microphone.driver"
#define kPlugIn_Icon "CardBridgeMicrophone.icns"
#define kHas_Driver_Name_Format false
#define kDevice_Name "CardBridge Microphone"
#define kDevice_IsHidden false
#define kDevice_HasInput true
#define kDevice_HasOutput false

// Companion loopback writer. CardBridge writes to this output-only device;
// both devices share BlackHole's ring buffer. It remains visible for now so
// PortAudio can open it without a custom Core Audio UID backend.
#define kDevice2_Name "CardBridge Microphone Feed"
#define kDevice2_IsHidden false
#define kDevice2_HasInput false
#define kDevice2_HasOutput true

#define kManufacturer_Name "Voltwake"
#define kNumber_Of_Channels 2
#define kSampleRates 16000, 48000

// Compatibility experiment: Core Audio reports this HAL device as USB. This
// changes the public transport property only; it does not create an IOKit USB
// node and must not be treated as equivalent to real UAC hardware.
#define kCardBridgeTransportType kAudioDeviceTransportTypeUSB
