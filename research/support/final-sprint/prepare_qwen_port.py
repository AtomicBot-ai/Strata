from pathlib import Path
import subprocess

repo=Path("Atomic-Turbine")
path="engine/src/program/generate.cpp"
base=subprocess.check_output(["git","-C",str(repo),"show","HEAD:"+path]).decode()
s=base.replace("#include <charconv>","#include <charconv>\n#include <random>")
marker="        // what the server's Monitor tab shows"
start=s.index(marker,s.index("const bool slot_read_cap ="))
s=s[:start]+'''        // The optional parent uses the third already allocated Metal session. Only
        // the other two sessions are exposed to requests and coalesced prompt reads.
        bool parent_slot_enabled = false;
#if defined(STRATA_GPU_METAL)
        if (const char* fork = std::getenv("TURBINE_QWEN_FORK"); fork && std::string(fork) == "1") {
            if (o.batch != 3 || use_mtp || batch_df2 || multi_gpu || !stages.empty() ||
                o.batch_groups > 1 || o.suffix_draft != 0 || o.vision || o.prompt_cache <= 0) {
                std::fprintf(stderr, "TURBINE_QWEN_FORK needs --batch 3, text, prompt caching, one Metal device, no drafter\\n");
                return 1;
            }
            parent_slot_enabled = true;
        }
#endif
        const int request_slots = parent_slot_enabled ? 2 : std::max(o.batch, 0);
'''+s[start:]
s=s.replace('" batch_slots=" + std::to_string(o.batch) +','" batch_slots=" + std::to_string(request_slots) +\n                                       (parent_slot_enabled ? " native_parent_fork=1" : "") +',1)
s=s.replace('M.budget("batch_slots", (int64_t) o.batch);','M.budget("batch_slots", (int64_t) request_slots);',1)
s=s.replace('std::vector<BSlot> bs((size_t) std::max(o.batch, 0));','std::vector<BSlot> bs((size_t) request_slots);',1)
s=s.replace('const int GS = piped ? o.batch / o.batch_groups : o.batch;','const int GS = piped ? o.batch / o.batch_groups : request_slots;',1)
i=s.index('        auto copy_to_slot =')
s=s[:i]+'''#if defined(STRATA_GPU_METAL)
        constexpr int parent_slot = 2;
        std::vector<int32_t> parent_ids;
        bool parent_cvec = false;
        uint64_t parent_generation = 0;
        if (parent_slot_enabled) {
            std::random_device random;
            parent_generation = (uint64_t(random()) << 32) ^ random();
        }
#endif
'''+s[i:]
i=s.index('            if (line.rfind("BGEN ", 0)',s.index('            bool bgen_rewritten ='))
s=s[:i]+'''#if defined(STRATA_GPU_METAL)
            if (line.rfind("STATE_", 0) == 0) {
                std::istringstream input(line);
                std::string command, location, extra;
                uint64_t handle = 0;
                input >> command;
                const bool drop = command == "STATE_DROP";
                const bool save_parent = command == "STATE_SAVE";
                if (!parent_slot_enabled) {
                    std::puts("ERR native parent fork disabled");
                } else if ((!drop && !(input >> location && location == "MAIN")) ||
                           (!drop && !save_parent && command != "STATE_RESTORE") ||
                           (!save_parent && !(input >> handle)) || input >> extra) {
                    std::puts("ERR invalid state command");
                } else if (!save_parent && (parent_ids.empty() || handle != parent_generation)) {
                    std::puts("ERR invalid snapshot handle");
                } else if (drop) {
                    std::vector<int32_t>().swap(parent_ids);
                    std::puts("DROPPED");
                } else if (save_parent && (!live_ok || live.empty() || !live_imgs.empty() || !parent_ids.empty() || nan_flush)) {
                    std::puts("ERR drop existing snapshot or check source");
                } else {
                    try {
                        // Stage host allocations first. A failed device copy is fatal because
                        // it may have changed only part of the destination GPU state.
                        std::vector<int32_t> ids(save_parent ? live : parent_ids);
                        if (!ver.wait_commit(err) ||
                            !strata::metal_engine::window_slot_copy_main(save_parent, parent_slot, ids.size(), false, err)) {
                            std::fprintf(stderr, "native parent state copy failed: %s\\n", err.c_str());
                            return 1;
                        }
                        if (save_parent) {
                            parent_ids.swap(ids);
                            parent_cvec = cvec_cached;
                            ++parent_generation;
                            std::printf("SAVED %llu %zu\\n", (unsigned long long)parent_generation, parent_ids.size());
                        } else {
                            conversations.take_reuse();
                            live.swap(ids);
                            live_imgs.clear();
                            checks.clear();
                            tail_ckpt_len = -1;
                            cvec_cached = parent_cvec;
                            live_ok = true;
                            std::printf("RESTORED %zu\\n", live.size());
                        }
                    } catch (const std::bad_alloc&) {
                        std::puts("ERR snapshot metadata allocation failed");
                    }
                }
                std::fflush(stdout);
                continue;
            }
#endif
'''+s[i:]
d=Path('.work/final-sprint/qwen-port');d.mkdir(exist_ok=True)
(d/'base.cpp').write_text(base)
(d/'product.cpp').write_text(s)
delta=subprocess.run(['diff','-u','--label','a/'+path,'--label','b/'+path,str(d/'base.cpp'),str(d/'product.cpp')],capture_output=True)
assert delta.returncode==1
(d/'qwen-state.patch').write_bytes(delta.stdout)
