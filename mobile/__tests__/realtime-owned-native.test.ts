import * as LocalAuthentication from "expo-local-authentication";
import * as ImagePicker from "expo-image-picker";
import {ImageManipulator,SaveFormat} from "expo-image-manipulator";
import {createOwnedNativePorts} from "../src/behaviors/owned-native";
jest.mock("expo-local-authentication",()=>({hasHardwareAsync:jest.fn(),isEnrolledAsync:jest.fn(),supportedAuthenticationTypesAsync:jest.fn(),authenticateAsync:jest.fn()}));
jest.mock("expo-image-picker",()=>({launchImageLibraryAsync:jest.fn()}));
jest.mock("expo-image-manipulator",()=>({ImageManipulator:{manipulate:jest.fn()},SaveFormat:{JPEG:"jpeg"}}));
const auth=LocalAuthentication as jest.Mocked<typeof LocalAuthentication>,picker=ImagePicker as jest.Mocked<typeof ImagePicker>;
beforeEach(()=>jest.clearAllMocks());
it("uses only the supplied credential namespace/read port, never the legacy store",async()=>{
 const read=jest.fn(async()=>"synthetic-only");const native=createOwnedNativePorts(read,"ios");expect(await native.readToken()).toBe("synthetic-only");expect(read).toHaveBeenCalledTimes(1);
});
it("preserves the public biometric prompt contract as separate checked awaits",async()=>{
 const native=createOwnedNativePorts(async()=>null,"ios");auth.hasHardwareAsync.mockResolvedValue(true);auth.isEnrolledAsync.mockResolvedValue(true);auth.supportedAuthenticationTypesAsync.mockResolvedValue([2]);auth.authenticateAsync.mockResolvedValue({success:true});
 await native.hasHardware();await native.isEnrolled();await native.supportedTypes();await native.unlock("Owned prompt");
 expect(auth.authenticateAsync).toHaveBeenCalledWith({cancelLabel:"Use password",disableDeviceFallback:true,promptMessage:"Owned prompt"});expect(auth.hasHardwareAsync).toHaveBeenCalledTimes(1);expect(auth.isEnrolledAsync).toHaveBeenCalledTimes(1);
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
