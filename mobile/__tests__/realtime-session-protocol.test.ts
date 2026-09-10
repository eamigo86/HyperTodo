declare const __dirname:string;
const fs=jest.requireActual<{readFileSync:(name:string,encoding:"utf8")=>string}>("fs");
const path=jest.requireActual<{join:(...parts:string[])=>string}>("path");
import {classifyAuth, parseObservation, parseAuthBody, utf8Bytes, SESSION_HEADERS} from "../src/realtime/session-protocol";

const A="hvs1."+"A".repeat(43);
const token="t".repeat(43);
const login=fs.readFileSync(path.join(__dirname,"../../backend/hyperview/fragments/login_transition.xml"),"utf8").replace("{{ biometric_token }}",token);
const logout=fs.readFileSync(path.join(__dirname,"../../backend/hyperview/fragments/logout_transition.xml"),"utf8");
const panel=(clear=false)=>`<view xmlns="https://hyperview.org/hyperview" id="login-panel">${clear?'<behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/>':''}<form id="login-form"><text-field name="username" value="Typed name"/></form></view>`;

it("classifies only exact origin, method and auth path",()=>{
 expect(classifyAuth("https://app.test/hv/login/","POST","https://app.test")).toBe("password");
 expect(classifyAuth("https://app.test/hv/biometric/login/","post","https://app.test")).toBe("biometric");
 expect(classifyAuth("https://app.test/hv/logout/","POST","https://app.test")).toBe("logout");
 for(const [url,method] of [["https://foreign.test/hv/login/","POST"],["https://app.test/hv/login/","GET"],["https://app.test/hv/login/extra/","POST"],["https://app.test/hv/settings/","POST"]])expect(classifyAuth(url,method,"https://app.test")).toBeNull();
});

it("accepts only the exact bounded observation schema and equal header binding",()=>{
 const headers=new Headers({[SESSION_HEADERS.binding]:A});
 expect(parseObservation(JSON.stringify({version:1,authenticated:true,binding:A}),headers)).toEqual({version:1,authenticated:true,binding:A});
 for(const value of [{version:1,authenticated:"true",binding:A},{version:1,authenticated:true,binding:A,username:"private"},{version:2,authenticated:true,binding:A},{version:1,authenticated:true,binding:"hvs1.bad"}])expect(()=>parseObservation(JSON.stringify(value),headers)).toThrow();
 expect(()=>parseObservation(JSON.stringify({version:1,authenticated:true,binding:A}),new Headers())).toThrow();
 expect(()=>parseObservation(" ".repeat(1025),headers)).toThrow();
});

it("consumes the actual login/logout template shapes without exposing successful HXML",()=>{
 expect(parseAuthBody("password",200,"password-ok",login)).toEqual({kind:"success",effect:{kind:"store",token}});
 expect(parseAuthBody("biometric",200,"biometric-ok",login)).toEqual({kind:"success",effect:{kind:"store",token}});
 expect(parseAuthBody("password",200,"password-ok",login.replace(token,""))).toEqual({kind:"success",effect:{kind:"clear"}});
 expect(parseAuthBody("logout",200,"logout-ok",logout)).toEqual({kind:"success",effect:null});
});

it("preserves refusal statuses and exact credential-clear policy",()=>{
 expect(parseAuthBody("password",422,"password-invalid",panel())).toMatchObject({kind:"panel",effect:null,body:panel()});
 expect(parseAuthBody("biometric",401,"biometric-invalid",panel(true))).toMatchObject({kind:"panel",effect:{kind:"clear"}});
 expect(parseAuthBody("biometric",429,"biometric-throttled",panel())).toMatchObject({kind:"panel",effect:null});
 expect(parseAuthBody("password",403,null,"CSRF verification failed")).toEqual({kind:"refused",effect:null,body:"CSRF verification failed"});
});

it.each([
 ["password",200,"biometric-ok",login],
 ["biometric",401,"biometric-invalid",panel()],
 ["biometric",429,"biometric-throttled",panel(true)],
 ["password",422,"password-invalid",panel(true)],
 ["password",200,"password-ok",login.replace(token,"invalid token")],
 ["password",200,"password-ok",login.replace('action="reload"','action="unknown"')],
 ["password",200,"password-ok",login.replace('</view>','<behavior trigger="load" action="store-biometric-token" token=""/></view>')],
 ["password",200,"password-ok","<!DOCTYPE view><view/>"],
 ["password",200,"password-ok","<broken"],
])("rejects malformed or mismatched auth metadata/body without an effect: %s/%s",(kind,status,outcome,body)=>{
 expect(()=>parseAuthBody(kind as "password",Number(status),String(outcome),String(body))).toThrow();
});

it("enforces the auth limit in UTF-8 bytes rather than Content-Length or code units",()=>{
 expect(utf8Bytes("Aé😀")).toBe(7);
 const padding=262144-utf8Bytes(login);
 expect(parseAuthBody("password",200,"password-ok",login+" ".repeat(padding)).kind).toBe("success");
 expect(()=>parseAuthBody("password",200,"password-ok",login+" ".repeat(padding-1)+"é")).toThrow();
 expect(()=>parseAuthBody("password",200,"password-ok",login+"\ud800")).toThrow();
});
