import * as LocalAuthentication from "expo-local-authentication";
import * as ImagePicker from "expo-image-picker";
import {ImageManipulator,SaveFormat} from "expo-image-manipulator";
import type {OwnedNativePorts} from "./owned";

/** Native APIs with one awaited stage per port; credentials always come from DI. */
export function createOwnedNativePorts(readCredential:()=>Promise<string|null>,platform:"ios"|"android"):OwnedNativePorts {
  return {
    platform,readToken:readCredential,
    hasHardware:()=>LocalAuthentication.hasHardwareAsync(),
    // The unlock prompt below demands strong biometrics, so only strong enrolment counts. isEnrolledAsync also
    // counts Android Class 2 (weak), and the offer would promise a sign-in the prompt then refuses. iOS reports
    // every enrolled biometric as strong, so it is unchanged.
    isEnrolled:async()=>(await LocalAuthentication.getEnrolledLevelAsync())===LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG,
    supportedTypes:()=>LocalAuthentication.supportedAuthenticationTypesAsync(),
    // "strong" is Android Class 3 only. The library default admits Class 2 (e.g. camera face unlock),
    // and this prompt releases a long-lived bearer credential. Ignored on iOS.
    unlock:promptMessage=>LocalAuthentication.authenticateAsync({cancelLabel:"Use password",disableDeviceFallback:true,biometricsSecurityLevel:"strong",promptMessage}),
    pick:async()=>{
      const result=await ImagePicker.launchImageLibraryAsync({mediaTypes:["images"],allowsEditing:true,aspect:[1,1],quality:1,exif:false});
      return result.canceled?{canceled:true}:{canceled:false,uri:result.assets[0]?.uri};
    },
    render:uri=>ImageManipulator.manipulate(uri).resize({width:512}).renderAsync(),
    save:image=>image.saveAsync({format:SaveFormat.JPEG,compress:0.8,base64:true}),
  };
}
