import bisect
import sys
from functools import total_ordering
import math

# enum for haplotypes
class Haplotypes:
    minus_infinity = -3
    conflict = -2
    unknown = -1
    paternal = 0
    maternal = 1
    infinity = 2
def is_known_haplotype(haplotype):
    return haplotype >= 0
# the operations below will set "." for all unphased haplotypes
def haplotype_to_string(haplotype):
    return str(haplotype) if is_known_haplotype(haplotype) else "."
def string_to_haplotype(haplotype_string):
    return Haplotypes.unknown if haplotype_string == "." else int(haplotype_string) 

# rules for updating one haplotype with another (merging)
def update_haplotype(haplotype_1, haplotype_2):
    if haplotype_1 == haplotype_2:
        return haplotype_1
    elif haplotype_1 == Haplotypes.unknown:
        return haplotype_2
    elif haplotype_2 == Haplotypes.unknown:
        return haplotype_1
    return Haplotypes.conflict

# a read segment (alignment)
@total_ordering
class Seg:
    
    def __init__(self, is_read2, query_start, query_end, ref_name, ref_start, ref_end, is_reverse, haplotype = Haplotypes.unknown):
        self.is_read2 = is_read2
        self.query_start = query_start
        self.query_end = query_end
        self.ref_name = ref_name
        self.ref_start = ref_start
        self.ref_end = ref_end
        self.is_reverse = is_reverse
        self.haplotype = haplotype # if not given, default is unknown
    
    # order: from left to right on the fragment
    # namely, read 1 before read 2
    # on read 1, order by left side
    # on read 2, order by minus right side
    def __lt__(self, other):
        return (self.is_read2, (-self.query_end if self.is_read2 else self.query_start)) < (other.is_read2, (-other.query_end if other.is_read2 else other.query_start))
    def __eq__(self, other):
        return (self.is_read2, (-self.query_end if self.is_read2 else self.query_start)) == (other.is_read2, (-other.query_end if other.is_read2 else other.query_start))

                
    def update_haplotype(self, is_read2, ref_name, ref_locus, haplotype):
        if self.is_read2 == is_read2 and self.ref_name == ref_name and ref_locus - 1 >= self.ref_start and ref_locus <= self.ref_end:
            self.haplotype = update_haplotype(self.haplotype, haplotype)
    
    def is_phased(self):
        return is_known_haplotype(self.haplotype)
    
    # output mapped loci of the left and right ends (ordered based on fragment)
    def ref_left(self):
        if self.is_read2 == self.is_reverse:
            return self.ref_start
        return self.ref_end

    def ref_right(self):
        if self.is_read2 == self.is_reverse:
            return self.ref_end
        return self.ref_start 
        
    def set_ref_left(self, ref_left):
        if self.is_read2 == self.is_reverse:
            self.ref_start = ref_left
        else:
            self.ref_end = ref_left

    def set_ref_right(self, ref_right):
        if self.is_read2 == self.is_reverse:
            self.ref_end = ref_right
        else:
            self.ref_start = ref_right
            
    def to_con_with(self, other):
        return Con(Leg(self.ref_name, self.ref_right(), self.haplotype), Leg(other.ref_name, other.ref_left(), other.haplotype))
    
    def to_string(self): # "m" is for mate
        return ",".join(["m" if self.is_read2 else ".", str(self.query_start), str(self.query_end), self.ref_name, str(self.ref_start), str(self.ref_end), "-" if self.is_reverse else "+", haplotype_to_string(self.haplotype)])

# create a segment from a string ("." will be set to unknown)
def string_to_seg(seg_string):
    is_read2, query_start, query_end, ref_name, ref_start, ref_end, is_reverse, haplotype = seg_string.split(",")
    is_read2 = True if is_read2 == "m" else False
    query_start = int(query_start)
    query_end = int(query_end)
    ref_start = int(ref_start)
    ref_end = int(ref_end)
    is_reverse = True if is_reverse == "-" else False
    haplotype = string_to_haplotype(haplotype)
    return Seg(is_read2, query_start, query_end, ref_name, ref_start, ref_end, is_reverse, haplotype)

# a read, containing all its segments
class Read:
    
    def __init__(self, name):
        self.name = name
        self.segs = []

    def add_seg(self, seg):
        self.segs.append(seg)
    
    def add_segs_from_read(self, read):
        self.segs += read.segs
    
    def num_segs(self):
        return len(self.segs)

    def num_phased_segs(self):
        num_phased_segs = 0
        for seg in self.segs:
            if seg.is_phased():
                num_phased_segs += 1
        return num_phased_segs
            
    def update_haplotype(self, is_read2, ref_name, ref_locus, haplotype):
        for seg in self.segs:
            seg.update_haplotype(is_read2, ref_name, ref_locus, haplotype)
            
    def sort_segs(self):
        self.segs.sort()
        
    def to_con_data(self, adjacent_only):
        self.sort_segs()
        con_data = ConData()
        for i in range(self.num_segs() - 1):
            for j in range(i + 1, self.num_segs()):
                if adjacent_only and j > i + 1:
                    break
                con_data.add_con(self.segs[i].to_con_with(self.segs[j]))
        return con_data
    
    def to_string(self):
        return self.name + "\t" + "\t".join([seg.to_string() for seg in self.segs])
        
# create a read from a string
def string_to_read(read_string):
    read_string_data = read_string.split("\t")
    read = Read(read_string_data[0])
    for seg_string in read_string_data[1:]:
        read.add_seg(string_to_seg(seg_string))
    return read

# a hash map of reads (a SEG file)
class SegData:
    
    def __init__(self):
        self.reads = {}

    def contains_read_name(self, name):
        return name in self.reads

    # add a read; merge if exists; ignore if empty
    def add_read(self, read):
        if read.num_segs() == 0:
            return # ignore empty reads
        if read.name not in self.reads: # add a new read
            self.reads[read.name] = read
        else: # add segments to an existing read
            self.reads[read.name].add_segs_from_read(read)
            
    # discard reads with a single segments
    def clean(self):
        for name in self.reads.keys():
            if self.reads[name].num_segs() < 2:
                del self.reads[name]
                
    # update haplotype for a specific read, if exists
    def update_haplotype(self, name, is_read2, ref_name, ref_locus, haplotype):
        if name in self.reads:
            self.reads[name].update_haplotype(is_read2, ref_name, ref_locus, haplotype)
            
    def num_reads(self):
        return len(self.reads)
        
    def num_segs(self):
        num_segs = 0
        for read in self.reads.values():
            num_segs += read.num_segs()
        return num_segs
    
    def num_phased_segs(self):
        num_phased_segs = 0
        for read in self.reads.values():
            num_phased_segs += read.num_phased_segs()
        return num_phased_segs
          
    def to_string(self): # no tailing new line
        return "\n".join(read.to_string() for read in self.reads.values())

# a leg
@total_ordering
class Leg:
    
    def __init__(self, ref_name, ref_locus, haplotype):
        self.ref_name = ref_name
        self.ref_locus = ref_locus
        self.haplotype = haplotype
        
    def __lt__(self, other):
        return (self.ref_name, self.ref_locus, self.haplotype) < (other.ref_name, other.ref_locus, other.haplotype)
    def __eq__(self, other):
        return (self.ref_name, self.ref_locus, self.haplotype) == (other.ref_name, other.ref_locus, other.haplotype)
        
    def get_ref_name(self):
        return self.ref_name
    def get_ref_locus(self):
        return self.ref_locus
    def is_phased(self):
        return is_known_haplotype(self.haplotype)
    def is_conflict(self):
        return self.haplotype == Haplotypes.conflict        
        
    def merge_with(self, other):
        self.ref_locus = (self.ref_locus + other.ref_locus)/2
        self.haplotype = update_haplotype(self.haplotype, other.haplotype)

    def same_chr_with(self, other):
        return self.ref_name == other.ref_name
        
    def separation_with(self, other):
        return abs(self.ref_locus - other.ref_locus)
    
    # check if a leg is in a region
    def in_reg(self, reg):
        if self.ref_name != reg.ref_name:
            return False
        if reg.has_haplotype and self.haplotype != reg.haplotype:
            return False
        if reg.has_start and self.ref_locus < reg.start:
            return False
        if reg.has_end and self.ref_locus > reg.end:
            return False
        return True
    # check if a leg is in a list of regions
    def in_regs(self, regs):
        for reg in regs:
            if self.in_reg(reg):
                return True
        return False
    # check if a leg is in a list of included regions, but not in a list of excluded regions
    def satisfy_regs(self, inc_regs, exc_regs):
        return self.in_regs(inc_regs) and not self.in_regs(exc_regs)
                        
    def to_string(self):
        return ",".join([self.ref_name, str(self.ref_locus), haplotype_to_string(self.haplotype)])

def string_to_leg(leg_string):
    ref_name, ref_locus, haplotype = leg_string.split(",")
    ref_locus = int(ref_locus)
    haplotype = string_to_haplotype(haplotype)
    return Leg(ref_name, ref_locus, haplotype)

# a list of legs, can be sorted to query number of legs in a region
class LegList:
    def __init__(self):
        self.legs = []
        self.is_sorted = True
    def num_legs(self):
        return(len(self.legs))
    def sort_legs(self):
        self.legs.sort()
        self.is_sorted = True
    def add_leg(self, leg):
        self.legs.append(leg)
        self.is_sorted = False
    def add_con_data(self, con_data):
        for con in con_data.get_cons():
            self.add_con(con)
            
    # query a leg, regardless of haplotypes, assume sorted and that the list includes the leg itself
    def is_leg_promiscuous(self, leg, max_leg_distance, max_leg_count):
        index_to_check = bisect.bisect_left(self.legs, Leg(leg.get_ref_name(), leg.get_ref_locus() - max_leg_distance, Haplotypes.minus_infinity)) + max_leg_count
        if index_to_check >= len(self.legs):
            return False
        return self.legs[index_to_check] <= Leg(leg.get_ref_name(), leg.get_ref_locus() + max_leg_distance, Haplotypes.infinity)
    
    def to_string(self):
        return "\n".join([leg.to_string() for leg in self.legs])

class LegData:
    def __init__(self):
        self.leg_lists = {}
        self.is_sorted = True
    def num_legs(self):
        num_legs = 0
        for leg_list in self.leg_lists.values():
            num_legs += leg_list.num_legs()
        return num_legs
    def add_empty_leg_list(self, ref_name):
        self.leg_lists[ref_name] = LegList()
    def add_leg(self, leg):
        if leg.get_ref_name() not in self.leg_lists:
            self.add_empty_leg_list(leg.get_ref_name())
        self.leg_lists[leg.get_ref_name()].add_leg(leg)
        self.is_sorted = False
    def add_con(self, con):
        self.add_leg(con.leg_1())
        self.add_leg(con.leg_2())   
    def add_con_data(self, con_data):
        for con in con_data.get_cons():
            self.add_con(con)
    def sort_legs(self):
        for leg_list in self.leg_lists.values():
            leg_list.sort_legs()
        self.is_sorted = True
        
    def is_leg_promiscuous(self, leg, max_leg_distance, max_leg_count):
        return self.leg_lists[leg.get_ref_name()].is_leg_promiscuous(leg, max_leg_distance, max_leg_count)
    

    def to_string(self):
        return "\n".join([self.leg_lists[ref_name].to_string() for ref_name in sorted(self.leg_lists.keys())])
        
# a contact (legs always sorted)
@total_ordering
class Con:
    def __init__(self, leg_1, leg_2):
        self.legs = sorted([leg_1, leg_2])
    
    def __eq__(self, other):
        return (self.legs[0], self.legs[1]) == (other.legs[0], other.legs[1])
    def __lt__(self, other):
        return (self.legs[0], self.legs[1]) < (other.legs[0], other.legs[1])
    
    def leg_1(self):
        return self.legs[0]
    def leg_2(self):
        return self.legs[1]
    def num_phased_legs(self):
        num_phased_legs = 0
        for i in range(2):
            if self.legs[i].is_phased():
                num_phased_legs += 1
        return num_phased_legs
    def num_conflict_legs(self):
        num_conflict_legs = 0
        for i in range(2):
            if self.legs[i].is_conflict():
                num_conflict_legs += 1
        return num_conflict_legs
    def ref_names(self):
        return tuple([leg.get_ref_name() for leg in self.legs])
    
    def sort_legs(self):
        self.legs.sort()
       
    def is_intra_chr(self):
        return self.leg_1().same_chr_with(self.leg_2())
    
    def separation(self):
        return self.leg_2().get_ref_locus() - self.leg_1().get_ref_locus()
        
    def merge_with(self, other):
        for i in range(2):
            self.legs[i].merge_with(other.legs[i])
        self.sort_legs()
    
    # different distance functions w. r. t. another contact, assuming the same chromosome
    def distance_leg_1_with(self, other):
        return self.leg_1().separation_with(other.leg_1())
    def distance_leg_2_with(self, other):
        return self.leg_2().separation_with(other.leg_2())
    def distance_inf_with(self, other): # L-inf norm
        return max(self.distance_leg_1_with(other), self.distance_leg_2_with(other))
    def distance_half_with(self, other): # L-1/2 norm
        return math.sqrt(self.distance_leg_1_with(other) ** 2 + distance_leg_2_with(other) ** 2)
            
    def satisfy_regs(self, inc_regs, exc_regs):
        return self.leg_1().satisfy_regs(inc_regs, exc_regs) and self.leg_2().satisfy_regs(inc_regs, exc_regs)
    
    def is_promiscuous(self, leg_data, max_leg_distance, max_leg_count):
        return leg_data.is_leg_promiscuous(self.leg_1(), max_leg_distance, max_leg_count) or leg_data.is_leg_promiscuous(self.leg_2(), max_leg_distance, max_leg_count)

    def to_string(self):
        return "\t".join([leg.to_string() for leg in self.legs])
def ref_names_to_string(ref_names):
    return ",".join(ref_names)

def string_to_con(con_string):
    leg_1, leg_2 = con_string.split("\t")
    return Con(string_to_leg(leg_1), string_to_leg(leg_2))

# a sorted list of contacts
class ConList:
    def __init__(self):
        self.cons = []
        self.is_sorted = True
    
    # generator for all its contacts
    def get_cons(self):
        for con in self.cons:
            yield con
        
    def num_cons(self):
        return(len(self.cons))
        
    def num_phased_legs(self):
        num_phased_legs = 0
        for con in self.cons:
            num_phased_legs += con.num_phased_legs()
        return num_phased_legs
    def num_conflict_legs(self):
        num_conflict_legs = 0
        for con in self.cons:
            num_conflict_legs += con.num_conflict_legs()
        return num_conflict_legs
    def num_intra_chr(self):
        num_intra_chr = 0
        for con in self.cons:
            if con.is_intra_chr():
                num_intra_chr += 1
        return num_intra_chr
                        
    def sort_cons(self):
        self.cons.sort()
        self.is_sorted = True
    
    def add_con(self, con):
        self.cons.append(con)
        self.is_sorted = False
    
    def merge_with(self, other):
        self.cons += other.cons
        if other.num_cons() > 0:
            self.is_sorted = False
        
    # remove intra-chromosomal contacts with small separations, no sorting needed
    def clean_separation(self, min_separation):
        self.cons[:] = [con for con in self.cons if not con.is_intra_chr() or con.separation() > min_separation]
    # remove contacts containing promiscuous legs
    def clean_promiscuous(self, leg_data, max_leg_distance, max_leg_count):
        self.cons[:] = [con for con in self.cons if not con.is_promiscuous(leg_data, max_leg_distance, max_leg_count)]

    # simple dedup within a read (no binary search), assuming the same chromosome
    def dedup_within_read(self, max_distance):
        while True:
            merged = False
            for i in range(len(self.cons)):
                for j in range(i + 1, len(self.cons)):
                    if self.cons[i].distance_inf_with(self.cons[j]) <= max_distance:
                        self.cons[i].merge_with(self.cons[j])
                        self.cons.pop(j)
                        merged = True
                        break
            if merged == False:
                break
        self.is_sorted = False
    
    # faster dedup, assuming the same chromosome
    def dedup(self, max_distance):
        self.cons.sort()
        while True:
            merged = False
            for i in range(len(self.cons)):
                for j in range(i + 1, len(self.cons)):
                    if self.cons[i].distance_leg_1_with(self.cons[j]) > max_distance:
                        break
                    if self.cons[i].distance_leg_2_with(self.cons[j]) <= max_distance:
                        self.cons[i].merge_with(self.cons[j])
                        self.cons.pop(j)
                        merged = True
                        break
            if merged == False:
                break
            self.cons[i:j] = sorted(self.cons[i:j])
        self.is_sorted = True
    
    def apply_regs(self, inc_regs, exc_regs):
        self.cons[:] = [con for con in self.cons if con.satisfy_regs(inc_regs, exc_regs)]
        
    def to_string(self):
        return "\n".join([con.to_string() for con in self.cons])
        
# a hashmap (tuples of two sorted chromosome names) of lists of contacts (a CON file)
class ConData:
    def __init__(self):
        self.con_lists = {}
        self.is_sorted = True
        
    # generator for all its cons, with ref_names sorted
    def get_cons(self):
        for ref_names in sorted(self.con_lists.keys()):
            for con in self.con_lists[ref_names].get_cons():
                yield con
    
    def add_empty_con_list(self, ref_names):
        self.con_lists[ref_names] = ConList()
    
    def add_con(self, con):
        if con.ref_names() not in self.con_lists:
            self.add_empty_con_list(con.ref_names())
        self.con_lists[con.ref_names()].add_con(con)
        self.is_sorted = False
    
    def merge_with(self, other):
        for ref_names in other.con_lists.keys():
            if ref_names in self.con_lists:
                self.con_lists[ref_names].merge_with(other.con_lists[ref_names])
                if not self.con_lists[ref_names].is_sorted:
                    self.is_sorted = False
            else:
                self.con_lists[ref_names] = other.con_lists[ref_names]
        
    # wrappers for all ConList operations
    def sort_cons(self):
        for con_list in self.con_lists.values():
            con_list.sort_cons()
        self.is_sorted = True
    def clean_separation(self, min_separation):
        for ref_names in self.con_lists.keys():
            self.con_lists[ref_names].clean_separation(min_separation)
            if self.con_lists[ref_names].num_cons() == 0:
                del self.con_lists[ref_names]
    def clean_promiscuous(self, leg_data, max_leg_distance, max_leg_count):
        for ref_names in self.con_lists.keys():
            self.con_lists[ref_names].clean_promiscuous(leg_data, max_leg_distance, max_leg_count)
            if self.con_lists[ref_names].num_cons() == 0:
                del self.con_lists[ref_names]
    def dedup_within_read(self, max_distance):
        for con_list in self.con_lists.values():
            con_list.dedup_within_read(max_distance)
        self.is_sorted = False
    def dedup(self, max_distance):
        for ref_names in self.con_lists.keys():
            sys.stderr.write("[M::" + __name__ + "] merging duplicates for chromosome pair (" + ref_names_to_string(ref_names) + "): " + str(self.con_lists[ref_names].num_cons()) + " putative contacts\n")
            self.con_lists[ref_names].dedup(max_distance)
        self.is_sorted = True
    def apply_regs(self, inc_regs, exc_regs):
        for ref_names in self.con_lists.keys():
            self.con_lists[ref_names].apply_regs(inc_regs, exc_regs)
            if self.con_lists[ref_names].num_cons() == 0:
                del self.con_lists[ref_names]
    def num_cons(self):
        num_cons = 0
        for con_list in self.con_lists.values():
            num_cons += con_list.num_cons()
        return num_cons
    def num_phased_legs(self):
        num_phased_legs = 0
        for con_list in self.con_lists.values():
            num_phased_legs += con_list.num_phased_legs()
        return num_phased_legs
    def num_conflict_legs(self):
        num_conflict_legs = 0
        for con_list in self.con_lists.values():
            num_conflict_legs += con_list.num_conflict_legs()
        return num_conflict_legs
    def num_intra_chr(self):
        num_intra_chr = 0
        for con_list in self.con_lists.values():
            num_intra_chr += con_list.num_intra_chr()
        return num_intra_chr
    
 
                         
    def to_string(self): # no tailing new line
        return "\n".join([self.con_lists[ref_names].to_string() for ref_names in sorted(self.con_lists.keys())])

def file_to_con_data(con_file):
    con_data = ConData()
    for con_file_line in con_file:
        con_data.add_con(string_to_con(con_file_line.strip()))
    return con_data

# augmented data for dedup: each leg records haplotypes of all duplicates
class DupLeg(Leg):
    def __init__(self, leg):
        Leg.__init__(self, leg.ref_name, leg.ref_locus, leg.haplotype)
        self.dups = {Haplotypes.unknown: 0, Haplotypes.paternal: 0, Haplotypes.maternal: 0}
        self.dups[leg.haplotype] += 1
    def num_dups(self):
        return sum(self.dups.values())
    def merge_with(self, other):
        Leg.merge_with(self, other)
        for haplotype in self.dups.keys():
            self.dups[haplotype] += other.dups[haplotype]
    #def to_string(self):
        #if self.haplotype != Haplotypes.conflict:
            #return ""
        #return Leg.to_string(self) + "(" + ",".join([str(self.dups[Haplotypes.unknown]), str(self.dups[Haplotypes.paternal]), str(self.dups[Haplotypes.maternal])]) + ")"

class DupCon(Con):
    def __init__(self, con):
        Con.__init__(self, DupLeg(con.legs[0]), DupLeg(con.legs[1]))
    def num_dups(self):
        return self.legs[0].num_dups() # should be the same for both legs

class DupConList(ConList):
    def __init__(self, con_list):
        ConList.__init__(self)
        for con in con_list.cons:
            self.add_con(DupCon(con))
    def dup_stats(self, display_max_num_dups):
        hist_num_dups = [0] * display_max_num_dups
        for dup_con in self.cons:
            hist_num_dups[min(dup_con.num_dups(), display_max_num_dups) - 1] += 1
        return hist_num_dups
        
class DupConData(ConData):
    def __init__(self, con_data):
        ConData.__init__(self)
        for ref_names in con_data.con_lists.keys():
            self.con_lists[ref_names] = DupConList(con_data.con_lists[ref_names])
            
    def dup_stats(self, display_max_num_dups):
        hist_num_dups = [0] * display_max_num_dups
        for con_list in self.con_lists.values():
            list_hist_num_dups = con_list.dup_stats(display_max_num_dups)
            for i in range(display_max_num_dups):
                hist_num_dups[i] += list_hist_num_dups[i]
        return hist_num_dups
        
    def add_empty_con_list(self, ref_names):
        self.con_lists[ref_names] = DupConList()
        
# print a histogram of counts to a string
def hist_num_to_string(hist_num):
    return "\n".join([(">=" if i == len(hist_num) - 1 else "") + str(i + 1) + "\t" + str(hist_num[i]) + " (" + str(round(100.0 * hist_num[i] / sum(hist_num), 2))+ "%)" for i in range(len(hist_num))])        
def hist_num_to_string_with_zero(hist_num):
    return "\n".join([(">=" if i == len(hist_num) - 1 else "") + str(i) + "\t" + str(hist_num[i]) + " (" + str(round(100.0 * hist_num[i] / sum(hist_num), 2))+ "%)" for i in range(len(hist_num))])        


# structures for included and excluded regions
class Reg:
    def __init__(self, ref_name):
        self.ref_name = ref_name
        self.has_haplotype = False
        self.has_start = False
        self.has_end = False
        self.haplotype = Haplotypes.unknown
        self.start = -1
        self.end = -1
    def add_haplotype(self, haplotype):
        if is_known_haplotype(haplotype):
            self.has_haplotype = True
            self.haplotype = haplotype
    def add_start(self, start):
        self.has_start = True
        self.start = start
    def add_end(self, end):
        self.has_start = True
        self.end = end
    def to_string(self):
        return "\t".join([self.ref_name, (haplotype_to_string(self.haplotype) if self.has_haplotype else "."), (str(self.start) if self.has_start else "."), (str(self.end) if self.has_end else ".")])

