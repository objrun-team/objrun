/** Next-boundary infrastructure guard; deliberately not imported by the frozen broker. */
export const GiB=1024**3;
export type DiskObservation={drive:string;driveType:number;freeBytes:number;observedAtMs:number};
export function evaluateDockerDisk(observation:DiskObservation|null,options:{nowMs:number;expectedDrive:string;plannedGrowthBytes?:number;minimumFreeBytes?:number;maximumAgeMs?:number}){
 const floor=options.minimumFreeBytes??8*GiB,growth=options.plannedGrowthBytes??0,ageLimit=options.maximumAgeMs??30000;
 if(!Number.isFinite(floor)||floor<5*GiB||!Number.isFinite(growth)||growth<0)throw Error('invalid_disk_policy');
 const block=(reason:string)=>({admissible:false,reason,minimumRequiredBytes:floor+growth,scoreCertificate:false});
 if(!observation)return block('physical_disk_measurement_unavailable');
 if(observation.drive.toUpperCase()!==options.expectedDrive.toUpperCase())return block('wrong_physical_docker_volume');
 if(observation.driveType!==3)return block('not_a_local_fixed_disk');
 if(!Number.isFinite(observation.freeBytes)||observation.freeBytes<0)return block('invalid_free_space');
 const age=options.nowMs-observation.observedAtMs;
 if(!Number.isFinite(age)||age<0||age>ageLimit)return block('stale_disk_measurement');
 if(observation.freeBytes<floor+growth)return block('docker_physical_disk_growth_reserve');
 return{admissible:true,reason:'current_local_docker_volume_has_growth_reserve',freeBytes:observation.freeBytes,minimumRequiredBytes:floor+growth,scoreCertificate:false};
}
export function observeDockerDisk(dockerDataPath:string):DiskObservation|null{
 const match=/^([a-z]):[\\/]/i.exec(dockerDataPath);if(!match)return null;
 const drive=match[1]!.toUpperCase()+':';
 const script=`Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${drive}'" | Select-Object DeviceID,DriveType,FreeSpace | ConvertTo-Json -Compress`;
 const result=Bun.spawnSync(['powershell.exe','-NoProfile','-NonInteractive','-Command',script]);
 if(result.exitCode!==0)return null;
 try{const value=JSON.parse(result.stdout.toString());if(!value)return null;return{drive:value.DeviceID,driveType:value.DriveType,freeBytes:Number(value.FreeSpace),observedAtMs:Date.now()};}catch{return null;}
}
