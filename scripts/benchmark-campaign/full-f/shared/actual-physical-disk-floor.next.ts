/** User-authorized actual-space floor; predicted growth is recorded, never admission. */
export const GiB=1024**3;
export type DiskObservation={drive:string;driveType:number;freeBytes:number;observedAtMs:number};
export function evaluateDockerDisk(observation:DiskObservation|null,options:{nowMs:number;expectedDrive:string;plannedGrowthBytes?:number;minimumFreeBytes?:number;maximumAgeMs?:number}){
 const floor=5*GiB,growth=options.plannedGrowthBytes??0,ageLimit=options.maximumAgeMs??30000;
 if(!Number.isFinite(floor)||floor<5*GiB||!Number.isFinite(growth)||growth<0)throw Error('invalid_disk_policy');
 const block=(reason:string)=>({admissible:false,reason,minimumRequiredBytes:floor,scoreCertificate:false});
 if(!observation)return block('physical_disk_measurement_unavailable');
 if(observation.drive.toUpperCase()!==options.expectedDrive.toUpperCase())return block('wrong_physical_docker_volume');
 if(observation.driveType!==3)return block('not_a_local_fixed_disk');
 if(!Number.isFinite(observation.freeBytes)||observation.freeBytes<0)return block('invalid_free_space');
 const age=options.nowMs-observation.observedAtMs;
 if(!Number.isFinite(age)||age<0||age>ageLimit)return block('stale_disk_measurement');
 if(observation.freeBytes<floor)return block('actual_disk_below_five_gib_floor');
 return{admissible:true,reason:'actual_local_volume_above_five_gib_floor',freeBytes:observation.freeBytes,minimumRequiredBytes:floor,scoreCertificate:false};
}
export function observeDockerDisk(dockerDataPath:string):DiskObservation|null{
 const match=/^([a-z]):[\\/]/i.exec(dockerDataPath);if(!match)return null;
 const drive=match[1]!.toUpperCase()+':';
 const script=`Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${drive}'" | Select-Object DeviceID,DriveType,FreeSpace | ConvertTo-Json -Compress`;
 let result;try{result=Bun.spawnSync(['powershell.exe','-NoProfile','-NonInteractive','-Command',script]);}catch{return null;}
 if(result.exitCode!==0)return null;
 try{const value=JSON.parse(result.stdout.toString());if(!value)return null;return{drive:value.DeviceID,driveType:value.DriveType,freeBytes:Number(value.FreeSpace),observedAtMs:Date.now()};}catch{return null;}
}
