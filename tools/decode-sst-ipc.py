#!/usr/bin/env python3
"""decode-sst-ipc.py <sst-ipc.tsv> -- decode the Windows cAVS 1.5 DSP IPC trace.

Field layouts verified against linux-source-7.0.0 sound/soc/intel/avs/messages.h
(avs_global_msg_type, avs_module_msg_type, avs_dma_type, avs_connector_node_id,
avs_modcfg_base, avs_audio_format, avs_copier_cfg, avs_peakvol_cfg).
"""
import sys, re

GLB = {1:"ROM_CONTROL", 15:"LOAD_MULTIPLE_MODULES", 16:"UNLOAD_MULTIPLE_MODULES",
       17:"CREATE_PIPELINE", 18:"DELETE_PIPELINE", 19:"SET_PIPELINE_STATE",
       20:"GET_PIPELINE_STATE", 24:"LOAD_LIBRARY", 27:"NOTIFICATION"}
MOD = {0:"INIT_INSTANCE", 3:"LARGE_CONFIG_GET", 4:"LARGE_CONFIG_SET", 5:"BIND",
       6:"UNBIND", 7:"SET_DX", 8:"SET_D0IX", 11:"DELETE_INSTANCE"}
DMA = {0:"HDA_HOST_OUTPUT", 1:"HDA_HOST_INPUT", 8:"HDA_LINK_OUTPUT",
       9:"HDA_LINK_INPUT", 11:"DMIC_LINK_INPUT", 12:"I2S_LINK_OUTPUT", 13:"I2S_LINK_INPUT"}
PPL = {0:"INVALID", 1:"UNINITIALIZED", 2:"RESET", 3:"PAUSED", 4:"RUNNING"}

def node(v):
    return f"node_id=0x{v:x} [dma_type={DMA.get((v>>8)&0x1f,(v>>8)&0x1f)} vindex={v&0xff}]"

def fmt(d):
    freq,depth,cmap,cfg,ilv,packed = d
    return (f"{freq} Hz / {depth}-bit / {packed&0xff}ch "
            f"(valid_bits={(packed>>8)&0xff} sample_type={(packed>>16)&0xff} "
            f"chan_map=0x{cmap:08x} chan_cfg={cfg} interleaving={ilv})")

def modcfg(d):
    out=[f"      cpc={d[0]} ibs={d[1]} obs={d[2]} is_pages={d[3]}",
         f"      in_fmt : {fmt(d[4:10])}"]
    if len(d)==21:                                   # avs_copier_cfg (84 B)
        out += [f"      out_fmt: {fmt(d[10:16])}",
                f"      feature_mask=0x{d[16]:x}",
                f"      GATEWAY: {node(d[17])} dma_buffer_size={d[18]} config_length={d[19]}"]
    elif len(d)>=10 and (len(d)-10)%6==0:            # avs_peakvol_cfg (40 B + n*24)
        for i in range(10,len(d),6):
            v=d[i:i+6]
            out.append(f"      vol[{(i-10)//6}]: channel_id=0x{v[0]:x} "
                       f"target_volume=0x{v[1]:08x} curve_type={v[2]} "
                       f"curve_duration={v[5]<<32|v[4]}")
    return out

def main(path):
    for line in open(path):
        line=line.rstrip("\n")
        if line.startswith("#") or not line.strip(): print(line); continue
        f=line.split("\t")
        if len(f)<5: print(line); continue
        seq,delta,dirn,op,rest=f[0],int(f[1]),f[2],f[3],f[4]
        toks=rest.replace("(null)","").split()
        try: pri=int(toks[0],16); ext=int(toks[1],16)
        except (ValueError,IndexError): print(line); continue
        if not pri>>31 & 1: continue                 # BUSY clear = the ack write, skip
        tgt=(pri>>30)&1; rsp=(pri>>29)&1; typ=(pri>>24)&0x1f; pay=pri&0xffffff
        data=[int(t,16) for t in toks[4:]] if len(toks)>4 else []
        tag="REPLY " if rsp else "REQ   "
        if tgt==0:
            name=GLB.get(typ,f"GLB_{typ}")
            det=""
            if typ==24: det=f"lib_id={(pay>>16)&0xff} dma_id={pay&0xffff}"
            elif typ==17: det=f"ppl_instance={(pay>>16)&0xff} priority={(pay>>11)&0x1f} mem_pages={pay&0x7ff}"
            elif typ==18: det=f"ppl_instance={(pay>>16)&0xff}"
            elif typ==19:
                det=f"state={PPL.get(pay&0xffff,pay&0xffff)}"
                if data: det+=f"  multi_ppl: count={data[0]} ids={data[1:]}"
            print(f"[{seq:>3}] +{delta:>9}us {tag}{name:<24} {det}")
        else:
            name=MOD.get(typ,f"MOD_{typ}")
            mid=pay&0xffff; inst=(pay>>16)&0xff
            det=f"module_id={mid} instance={inst}"
            if typ==0:
                det+=f"  ppl_instance={(ext>>16)&0xff} core={(ext>>24)&0xf} param_dwords={ext&0xffff}"
            elif typ in (5,6):
                det+=f"  -> dst_module_id={ext&0xffff} dst_instance={(ext>>16)&0xff} " \
                     f"dst_queue={(ext>>24)&0x7} src_queue={(ext>>27)&0x7}"
            print(f"[{seq:>3}] +{delta:>9}us {tag}{name:<24} {det}")
            if typ==0 and data:
                for l in modcfg(data): print(l)

main(sys.argv[1] if len(sys.argv)>1 else "windows-trip-2026-08-22/results-tripC/sst-ipc.tsv")
