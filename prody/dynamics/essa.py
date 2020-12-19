from os import chdir, listdir, mkdir, system
from os.path import isdir
from pickle import dump
from re import findall
from numpy import argsort, array, c_, count_nonzero, hstack, mean, median, quantile, save
from scipy.stats import zscore, median_absolute_deviation
import matplotlib.pyplot as plt
from prody import LOGGER
from prody.atomic.functions import extendAtomicData
from .anm import ANM
from .gnm import GNM
from prody.proteins import parsePDB, writePDB
from .editing import reduceModel
from .plotting import showAtomicLines
from .signature import ModeEnsemble, saveModeEnsemble
from prody.utilities import which


__all__ = ['ESSA']


class ESSA:

    '''
    ESSA determines the essentiality score of each residue based on the extent to which it can alter the global dynamics ([KB20]_). It can also rank potentially allosteric pockets by calculating their ESSA and local hydrophibic density z-scores using Fpocket algorithm ([LGV09]_). 

    .. [KB20] Kaynak B.T., Bahar I., Doruker P., Essential site scanning analysis: A new approach for detecting sites that modulate the dispersion of protein global motions, *Comput. Struct. Biotechnol. J.* **2020** 18:1577-1586.

    .. [LGV09] Le Guilloux, V., Schmidtke P., Tuffery P., Fpocket: An open source platform for ligand pocket detection, *BMC Bioinformatics* **2009** 10:168.

    Instantiate an ESSA object.
    '''

    def __init__(self):

        self._atoms = None
        self._title = None
        self._lig = None
        self._heavy = None
        self._ca = None
        self._n_modes = None
        self._enm = None
        self._cutoff = None
        self._lig = None
        self._lig_idx = None
        self._dist = None
        self._ensemble = None
        self._labels = None
        self._zscore = None

    def setSystem(self, atoms, **kwargs):

        '''
        Sets atoms, ligands and a cutoff distance for protein-ligand interactions.

        :arg atoms: *atoms* parsed by parsePDB

        :arg lig: String of ligands' chainIDs and resSeqs (resnum) separated by a whitespace,
            e.g., 'A 300 B 301'. Default is None.
        :type lig: str

        :arg dist: Atom-atom distance (A) to select the protein residues that are in contact with a ligand, default is 4.5 A.
        :type dist: float
        '''

        self._atoms = atoms
        self._title = atoms.getTitle()
        self._lig = kwargs.pop('lig', None)
        if self._lig:
            self._lig_idx = {}
            self._dist = kwargs.pop('dist', 4.5)

        self._heavy = atoms.select('protein and heavy and not hetatm')
        self._ca = self._heavy.ca

        # --- residue indices of protein residues that are within dist (4.5 A) of ligands --- #

        if self._lig:
            ligs = self._lig.split()
            ligs = list(zip(ligs[::2], ligs[1::2]))
            for chid, resnum in ligs:
                key = ''.join(chid + str(resnum))
                sel_lig = 'calpha and not hetatm and (same residue as ' \
                          f'exwithin {self._dist} of (chain {chid} and resnum {resnum}))'
                self._lig_idx[key] = self._atoms.select(sel_lig).getResindices()

    def scanResidues(self, n_modes=10, enm='gnm', cutoff=None):

        '''
        Scans residues to generate ESSA z-scores.

        :arg n_modes: Number of global modes.
        :type n_modes: int

        :arg enm: Type of elastic network model, 'gnm' or 'anm', default is 'gnm'.
        :type enm: str

        :arg cutoff: Cutoff distance (A) for pairwise interactions, default is 10 A for GNM and 15 A for ANM.
        :type cutoff: float
        '''

        self._n_modes = n_modes
        self._enm = enm

        self._ensemble = ModeEnsemble(f'{self._title}')
        self._ensemble.setAtoms(self._ca)
        self._labels = ['ref']

        # --- reference model --- #

        if self._enm == 'gnm':
            ca_enm = GNM('ca')
            if cutoff is not None:
                self._cutoff = cutoff
                ca_enm.buildKirchhoff(self._ca, cutoff=self._cutoff)
            else:
                ca_enm.buildKirchhoff(self._ca)
                self._cutoff = ca_enm.getCutoff()

        if self._enm == 'anm':
            ca_enm = ANM('ca')
            if cutoff is not None:
                self._cutoff = cutoff
                ca_enm.buildHessian(self._ca, cutoff=self._cutoff)
            else:
                ca_enm.buildHessian(self._ca)
                self._cutoff = ca_enm.getCutoff()

        ca_enm.calcModes(n_modes=n_modes)
        self._ensemble.addModeSet(ca_enm[:])

        # --- perturbed models --- #

        LOGGER.progress(msg='', steps=(self._ca.numAtoms()))
        for i in self._ca.getResindices():
            LOGGER.update(step=i+1, msg=f'scanning residue {i+1}')
            sel = f'calpha or resindex {i}'
            tmp = self._heavy.select(sel)

            if self._enm == 'gnm':
                tmp_enm = GNM(f'res_{i}')
                tmp_enm.buildKirchhoff(tmp, cutoff=self._cutoff)

            if self._enm == 'anm':
                tmp_enm = ANM(f'res_{i}')
                tmp_enm.buildHessian(tmp, cutoff=self._cutoff)

            tmp_enm_red, _ = reduceModel(tmp_enm, tmp, self._ca)
            tmp_enm_red.calcModes(n_modes=self._n_modes)

            self._ensemble.addModeSet(tmp_enm_red[:])
            self._labels.append(tmp_enm.getTitle())

        self._ensemble.setLabels(self._labels)
        self._ensemble.match()

        # --- ESSA computation part --- #

        denom = self._ensemble[0].getEigvals()
        num = self._ensemble[1:].getEigvals() - denom

        eig_diff = num / denom * 100
        eig_diff_mean = mean(eig_diff, axis=1)

        self._zscore = zscore(eig_diff_mean)

    def getESSAZscores(self):

        'Returns ESSA z-scores.'

        return self._zscore

    def getESSAEnsemble(self):

        'Returns ESSA mode ensemble, comprised of ENMS calculated for each scanned/perturbed residue.'

        return self._ensemble[:]
    
    def saveESSAEnsemble(self):

        'Saves ESSA mode ensemble, comprised of ENMS calculated for each scanned/perturbed residue.'

        saveModeEnsemble(self._ensemble, filename=f'{self._title}_{self._enm}')

    def saveESSAZscores(self):

        'Saves ESSA z-scores to a binary file in Numpy `.npy` format.'

        save(f'{self._title}_{self._enm}_zs', self._zscore)

    def writeESSAZscoresToPDB(self):

        'Writes a pdb file with ESSA z-scores placed in the B-factor column.'

        writePDB(f'{self._title}_{self._enm}_zs', self._heavy,
                 beta=extendAtomicData(self._zscore, self._ca, self._heavy)[0])

    def getLigandResidueIndices(self):

        'Returns indices of the residues interacting with ligands.'

        if self._lig:
            return self._lig_idx
        else:
            LOGGER.warning('No ligand provided.')

    def saveLigandResidueIndices(self):

        'Saves indices of the residues interacting with ligands.'

        if self._lig:
            dump(self._lig_idx, open(f'{self._title}_ligand_resindices.pkl', 'wb'))
        else:
            LOGGER.warning('No ligand provided.')

    def showESSAProfile(self, quant=.75):

        '''
        Shows ESSA profile.

        :arg quant: Quantile value to plot a baseline for z-scores, default is 0.75.
        :type quant: float
        '''

        showAtomicLines(self._zscore, atoms=self._ca, c='k', linewidth=1.)

        if self._lig:
            zs_lig = {k: self._zscore[v] for k, v in self._lig_idx.items()}
            for k in self._lig_idx.keys():
                plt.scatter(self._lig_idx[k], zs_lig[k], label=k)
            plt.legend()
        plt.hlines(quantile(self._zscore, q=quant),
                   xmin=0., xmax=self._ca.numAtoms(),
                   linestyle='--', color='c')

        plt.xlabel('Residue')
        plt.ylabel('Z-Score')

        plt.tight_layout()

    def scanPockets(self):

        'Generates ESSA z-scores for pockets and parses pocket features. It requires both Fpocket 3.0 and Pandas being installed in your system.'

        fpocket = which('fpocket')

        if fpocket is None:
            LOGGER.warning('Fpocket 3.0 was not found, please install it.')
            return None

        try:
            from pandas import Index, DataFrame
        except ImportError as ie:
            LOGGER.warning(ie.__str__() + ' was found, please install it.')
            return None

        rcr = {(i, j): k for i, j, k in zip(self._ca.getChids(),
                                            self._ca.getResnums(),
                                            self._ca.getResindices())}

        writePDB(f'{self._title}_pro', self._heavy)

        direc = f'{self._title}_pro_out'
        if not isdir(direc):
            system(f'fpocket -f {self._title}_pro.pdb')

        chdir(direc + '/pockets')
        l = [x for x in listdir('.') if x.endswith('.pdb')]
        l.sort(key=lambda x:int(x.partition('_')[0][6:]))

        ps = []
        for x in l:
            with open(x, 'r') as f:
                tmp0 = f.read()
                tmp1 = [(x[1].strip(), float(x[2])) for x in findall(r'(\w+\s\w+\s*-\s*)(.+):\s*([\d.-]+)(\n)', tmp0)]
            fea, sco = list(zip(*tmp1))
            ps.append(sco)
        pdbs = parsePDB(l)
        chdir('../..')

        # ----- # ----- #

        ps = array(ps)

        pcn = {int(pdb.getTitle().partition('_')[0][6:]):
               set(zip(pdb.getChids().tolist(),
                       pdb.getResnums().tolist())) for pdb in pdbs}
        pi = {p: [rcr[x] for x in crn] for p, crn in pcn.items()}

        pzs_max = {k: max(self._zscore[v]) for k, v in pi.items()}
        pzs_med = {k: median(self._zscore[v]) for k, v in pi.items()}

        # ----- # ----- #

        indices = Index(range(1, ps.shape[0] + 1), name='Pocket #')

        columns = Index(fea, name='Feature')

        self._df = DataFrame(index=indices, columns=columns, data=ps)

        # ----- # ----- #

        columns_zs = Index(['ESSA_max',
                            'ESSA_med',
                            'LHD'],
                           name='Z-score')

        zps = c_[list(pzs_max.values())]
        zps = hstack((zps, c_[list(pzs_med.values())]))
        zps = hstack((zps, zscore(self._df[['Local hydrophobic density Score']])))


        self._df_zs = DataFrame(index=indices, columns=columns_zs, data=zps)

    def rankPockets(self):

        'Ranks pockets in terms of their allosteric potential, based on their ESSA z-scores (max/median) with local hydrophobic density (LHD) screening.'

        from pandas import DataFrame, Index

        lhd = self._df_zs.loc[:, 'LHD']
        n = count_nonzero(lhd >= 0.)
        q = quantile(lhd, q=.85)

        # ----- # ------ #

        s_max = ['ESSA_max', 'LHD']

        zf_max = self._df_zs[s_max].copy()

        if n >= lhd.size // 4:
            f_max = zf_max.iloc[:, 1] >= 0.
        else:
            f_max = zf_max.iloc[:, 1] >= q

        zf_max = zf_max[f_max]

        zf_max.iloc[:, 0] = zf_max.iloc[:, 0].round(1)
        zf_max.iloc[:, 1] = zf_max.iloc[:, 1].round(2)

        self._idx_max = zf_max.sort_values(s_max, ascending=False).index

        # ----- # ----- #

        s_med = ['ESSA_med',
                 'LHD']

        zf_med = self._df_zs[s_med].copy()

        if n >= lhd.size // 4:
            f_med = zf_med.iloc[:, 1] >= 0.
        else:
            f_med = zf_med.iloc[:, 1] >= q

        zf_med = zf_med[f_med]

        zf_med.iloc[:, 0] = zf_med.iloc[:, 0].round(1)
        zf_med.iloc[:, 1] = zf_med.iloc[:, 1].round(2)

        self._idx_med = zf_med.sort_values(s_med, ascending=False).index

        ranks = Index(range(1, zf_max.shape[0] + 1), name='Allosteric potential / Rank')

        self._pocket_ranks = DataFrame(index=ranks, columns=['Pocket # (ESSA_max & LHD)',
                                                             'Pocket # (ESSA_med & LHD)'])

        self._pocket_ranks.iloc[:, 0] = self._idx_max
        self._pocket_ranks.iloc[:, 1] = self._idx_med

    def getPocketFeatures(self):

        'Returns pocket features as a Pandas dataframe.'

        return self._df

    def getPocketZscores(self):

        'Returns ESSA and local hydrophobic density (LHD) z-scores for pockets as a Pandas dataframe.'

        return self._df_zs

    def getPocketRanks(self):

        'Returns pocket ranks (allosteric potential).'

        return self._pocket_ranks
    
    def showPocketZscores(self):

        'Plots maximum/median ESSA and local hydrophobic density (LHD) z-scores for pockets.'

        with plt.style.context({'xtick.major.size': 10, 'xtick.labelsize': 30,
                                'ytick.major.size': 10, 'ytick.labelsize': 30,
                                'axes.labelsize': 35, 'legend.fontsize': 25,
                                'legend.title_fontsize': 0}):
            self._df_zs[['ESSA_max',
                         'ESSA_med',
                         'LHD']].plot.bar(figsize=(25, 10))
            plt.xticks(rotation=0)
            plt.xlabel('Pocket')
            plt.ylabel('Z-score')
            plt.tight_layout()

    def savePocketFeatures(self):

        'Saves pocket features to a pickle `.pkl` file.'

        self._df.to_pickle(f'{self._title}_pocket_features.pkl')

    def savePocketZscores(self):

        'Saves ESSA and local hydrophobic density (LHD) z-scores of pockets to a pickle `.pkl` file.'

        self._df_zs.to_pickle(f'{self._title}_pocket_zscores.pkl')

    def savePocketRanks(self):

        'Saves pocket ranks to a binary file in Numpy `.npy` format.'

        save(f'{self._title}_{self._enm}_pocket_ranks_wrt_ESSAmax_LHD',
             self._idx_max)
        save(f'{self._title}_{self._enm}_pocket_ranks_wrt_ESSAmed_LHD',
             self._idx_med)
        
    def writePocketRanksToCSV(self):

        'Writes pocket ranks to a `.csv` file.'

        self._pocket_ranks.to_csv(f'{self._title}_{self._enm}_pocket_ranks.csv', index=False)
