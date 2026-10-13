import * as SecureStore from "expo-secure-store";
import {sessionCredentials,createSessionCredentialPort} from "../src/biometrics/store";
import {createSessionEffects} from "../src/realtime/session-effects";
jest.mock("expo-secure-store",()=>({WHEN_UNLOCKED_THIS_DEVICE_ONLY:5,getItemAsync:jest.fn(),setItemAsync:jest.fn(),deleteItemAsync:jest.fn()}));
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
beforeEach(()=>jest.resetAllMocks());

it("shares the existing native queue without recursive enqueue or duplicated writes",async()=>{
 const read=deferred<string|null>();jest.mocked(SecureStore.getItemAsync).mockReturnValueOnce(read.promise);const first=sessionCredentials.read();const effects=createSessionEffects(sessionCredentials.storage);const next=effects.apply({},()=>true,{kind:"store",token:"issued-token"});
 await Promise.resolve();expect(SecureStore.setItemAsync).not.toHaveBeenCalled();read.resolve(null);await first;await expect(next).resolves.toBe("stored");
 expect(SecureStore.setItemAsync).toHaveBeenCalledTimes(1);expect(SecureStore.setItemAsync).toHaveBeenCalledWith("hypertodo.biometric.token","issued-token",{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY});
});

it("exposes a raw clear failure to the owner instead of swallowing it",async()=>{
 jest.mocked(SecureStore.deleteItemAsync).mockRejectedValue(new Error("keychain refused"));
 await expect(sessionCredentials.storage.enqueue(store=>store.clear())).rejects.toThrow("keychain refused");
});

it("orders writes on one chain and never runs a stale clear",async()=>{
 const write=deferred<void>();jest.mocked(SecureStore.setItemAsync).mockReturnValueOnce(write.promise);const old=sessionCredentials.storage.enqueue(store=>store.save("earlier"));let current=true;
 const next=createSessionEffects(sessionCredentials.storage).apply({},()=>current,{kind:"clear"});await Promise.resolve();current=false;write.resolve();await old;await expect(next).resolves.toBe("stale");expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
});

// The reset login panel starts a wipe and a probe read in the same load. A read that overtakes the wipe would reveal a
// sign-in button backed by a token the server already rejected.
it("never lets a read overtake an in-flight clear",async()=>{
 const wipe=deferred<void>();jest.mocked(SecureStore.deleteItemAsync).mockReturnValueOnce(wipe.promise);jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
 const clearing=sessionCredentials.storage.enqueue(store=>store.clear());const reading=sessionCredentials.read();
 await Promise.resolve();await Promise.resolve();expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
 wipe.resolve();await clearing;await expect(reading).resolves.toBeNull();expect(SecureStore.getItemAsync).toHaveBeenCalledTimes(1);
});

it("isolates fixture credential reads/writes on its captured namespace while sharing serialization",async()=>{
 const fixture=createSessionCredentialPort("fixture.synthetic.run-unique");jest.mocked(SecureStore.getItemAsync).mockResolvedValue("synthetic");
 expect(await fixture.read()).toBe("synthetic");await fixture.storage.enqueue(store=>store.save("test-only"));await fixture.storage.enqueue(store=>store.clear());
 expect(SecureStore.getItemAsync).toHaveBeenCalledWith("fixture.synthetic.run-unique");expect(SecureStore.setItemAsync).toHaveBeenCalledWith("fixture.synthetic.run-unique","test-only",{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY});expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith("fixture.synthetic.run-unique");
 for(const mock of [SecureStore.getItemAsync,SecureStore.setItemAsync,SecureStore.deleteItemAsync])expect(jest.mocked(mock).mock.calls.every(call=>call[0]!=="hypertodo.biometric.token")).toBe(true);
});

it("does not turn a failed modern credential read into a destructive missing-token clear",async()=>{
 const fixture=createSessionCredentialPort("fixture.synthetic.run-unique");jest.mocked(SecureStore.getItemAsync).mockRejectedValue(new Error("locked"));await expect(fixture.read()).rejects.toThrow("locked");expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
});
