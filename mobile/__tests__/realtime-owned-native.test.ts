import * as LocalAuthentication from "expo-local-authentication";
import * as ImagePicker from "expo-image-picker";
import {ImageManipulator,SaveFormat} from "expo-image-manipulator";
import {createOwnedNativePorts} from "../src/behaviors/owned-native";
jest.mock("expo-local-authentication",()=>({hasHardwareAsync:jest.fn(),isEnrolledAsync:jest.fn(),getEnrolledLevelAsync:jest.fn(),supportedAuthenticationTypesAsync:jest.fn(),authenticateAsync:jest.fn(),SecurityLevel:{NONE:0,SECRET:1,BIOMETRIC_WEAK:2,BIOMETRIC_STRONG:3}}));
jest.mock("expo-image-picker",()=>({launchImageLibraryAsync:jest.fn()}));
jest.mock("expo-image-manipulator",()=>({ImageManipulator:{manipulate:jest.fn()},SaveFormat:{JPEG:"jpeg"}}));
const auth=LocalAuthentication as jest.Mocked<typeof LocalAuthentication>,picker=ImagePicker as jest.Mocked<typeof ImagePicker>;
beforeEach(()=>jest.clearAllMocks());
it("uses only the supplied credential namespace/read port, never the legacy store",async()=>{
 const read=jest.fn(async()=>"synthetic-only");const native=createOwnedNativePorts(read,"ios");expect(await native.readToken()).toBe("synthetic-only");expect(read).toHaveBeenCalledTimes(1);
});
it("preserves the public biometric prompt contract as separate checked awaits",async()=>{
 const native=createOwnedNativePorts(async()=>null,"ios");auth.hasHardwareAsync.mockResolvedValue(true);auth.isEnrolledAsync.mockResolvedValue(true);auth.supportedAuthenticationTypesAsync.mockResolvedValue([2]);auth.authenticateAsync.mockResolvedValue({success:true});
 await native.hasHardware();expect(await native.isEnrolled()).toBe(true);await native.supportedTypes();await native.unlock("Owned prompt");
 expect(auth.authenticateAsync).toHaveBeenCalledWith({cancelLabel:"Use password",disableDeviceFallback:true,biometricsSecurityLevel:"strong",promptMessage:"Owned prompt"});expect(auth.hasHardwareAsync).toHaveBeenCalledTimes(1);expect(auth.isEnrolledAsync).toHaveBeenCalledTimes(1);expect(auth.getEnrolledLevelAsync).not.toHaveBeenCalled();
});
// The unlock prompt demands strong biometrics (Android Class 3) and otherwise falls back to the password form, so an
// enrolment offer for a device with only Class 2 (weak) biometrics would promise a sign-in the prompt then refuses.
// isEnrolledAsync counts weak biometrics too. iOS reports every enrolled biometric as strong, so it is unchanged.
it.each([
 ["nothing",LocalAuthentication.SecurityLevel.NONE,false],
 ["only a PIN, pattern or password",LocalAuthentication.SecurityLevel.SECRET,false],
 ["only weak (Class 2) biometrics",LocalAuthentication.SecurityLevel.BIOMETRIC_WEAK,false],
 ["strong biometrics",LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG,true],
])("treats a device enrolled with %s as strongly enrolled: %s",async(_label,level,expected)=>{
 const native=createOwnedNativePorts(async()=>null,"android");auth.isEnrolledAsync.mockResolvedValue(true);auth.getEnrolledLevelAsync.mockResolvedValue(level);
 expect(await native.isEnrolled()).toBe(expected);expect(auth.isEnrolledAsync).not.toHaveBeenCalled();
});
// iOS has no weak biometrics to exclude, and while Face ID or Touch ID is locked out after failed attempts
// getEnrolledLevelAsync answers SECRET although the biometry is still enrolled. Asking for the level there hid the
// offer during a lockout, where it used to show and the tap explained that the password is needed.
it.each([
 ["enrolled",true,LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG],
 ["enrolled but locked out, which the level reports as a PIN only",true,LocalAuthentication.SecurityLevel.SECRET],
 ["not enrolled",false,LocalAuthentication.SecurityLevel.NONE],
])("asks iOS only whether biometry is enrolled: %s",async(_label,enrolled,level)=>{
 const native=createOwnedNativePorts(async()=>null,"ios");auth.isEnrolledAsync.mockResolvedValue(enrolled);auth.getEnrolledLevelAsync.mockResolvedValue(level);
 expect(await native.isEnrolled()).toBe(enrolled);expect(auth.getEnrolledLevelAsync).not.toHaveBeenCalled();
});
it("lets an enrolment failure on iOS reach the probe too",async()=>{
 const native=createOwnedNativePorts(async()=>null,"ios");auth.isEnrolledAsync.mockRejectedValue(new Error("unavailable"));
 await expect(native.isEnrolled()).rejects.toThrow("unavailable");
});
it("lets an enrolment level failure reach the probe, which then offers nothing",async()=>{
 const native=createOwnedNativePorts(async()=>null,"android");auth.getEnrolledLevelAsync.mockRejectedValue(new Error("unavailable"));
 await expect(native.isEnrolled()).rejects.toThrow("unavailable");
});
it("keeps picker crop/privacy and JPEG resize in three separately guarded native stages",async()=>{
 const native=createOwnedNativePorts(async()=>null,"android");picker.launchImageLibraryAsync.mockResolvedValue({canceled:false,assets:[{uri:"file://test"}]} as ImagePicker.ImagePickerResult);
 const image={saveAsync:jest.fn(async()=>({base64:"safe"}))};const context={resize:jest.fn(),renderAsync:jest.fn(async()=>image)};context.resize.mockReturnValue(context);(ImageManipulator.manipulate as jest.Mock).mockReturnValue(context);
 expect(await native.pick()).toEqual({canceled:false,uri:"file://test"});expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith({mediaTypes:["images"],allowsEditing:true,aspect:[1,1],quality:1,exif:false});
 const rendered=await native.render("file://test");expect(context.resize).toHaveBeenCalledWith({width:512});expect(image.saveAsync).not.toHaveBeenCalled();await native.save(rendered);expect(image.saveAsync).toHaveBeenCalledWith({format:SaveFormat.JPEG,compress:0.8,base64:true});
});
it("preserves native cancellation/failure without laundering a result",async()=>{
 const native=createOwnedNativePorts(async()=>null,"ios");picker.launchImageLibraryAsync.mockResolvedValue({canceled:true,assets:null});expect(await native.pick()).toEqual({canceled:true});auth.hasHardwareAsync.mockRejectedValue(new Error("not available"));await expect(native.hasHardware()).rejects.toThrow("not available");
});
