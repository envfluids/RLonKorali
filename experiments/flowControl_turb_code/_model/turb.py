#from numpy import pi
import numpy as np
import time as time
from scipy.io import loadmat,savemat
import scipy as sp
from scipy.interpolate import RectBivariateSpline
from split2d import split2d
from split2d import pickcenter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['image.cmap'] = 'bwr'
from scipy.stats import multivariate_normal

np.seterr(over='raise', invalid='raise')

from py2d.eddy_viscosity_models import Tau_eddy_viscosity 
from py2d.convert import Tau2PiOmega_2DFHIT

# ---------------------- Forced turb
#lim = int(SPIN_UP ) # Start saving
#st = int( 1. / dt ) # How often to save data
NNSAVE = 10 
#
class turb:
    #
    # Solution of the 2D tub
    # Solve 2D turbulence by Fourier-Fourier pseudo-spectral method
    # Navier-Stokes equation is in the vorticity-stream function form
    #
    # u_t + ...  = 0,
    # with ... doubly periodic BC on ... .
    #
    # The nature of the solution depends on the Re=1/nu
    # condition u(x,0).  Energy enters the system

    #
    def __init__(self, 
                Lx=2.0*np.pi, Ly=2.0*np.pi, 
                NX=128,       NY=128, 
                dt=5e-4, 
                Re=20e3, rho=1.0, alpha=0.1, beta=0.0, 
                nsteps= None, 
                tend= 1.5000, 
                RL= False, 
                nActions= 1, 
                case='1', 
                rewardtype='k1', 
                statetype='enstrophy',
                actiontype='CL',
                nagents=16,
                spec_type = 'both'):
        #
        print('__init__')
        print('rewardtype', rewardtype[0:2])
        print('number of Actions=', nActions)
        print('number of Agents=', nagents)

        self.tic = time.time()
        if rewardtype[0]=='z':
            self.rewardtype ='enstrophy'
        elif rewardtype[0]=='k':
            self.rewardtype ='energy'
        if rewardtype[1]=='1':
            self.rewardfunc = '1'
        elif rewardtype[1]=='e':
            self.rewardfunc = 'e'
        elif rewardtype[1]=='c':
            self.rewardfunc = 'c'
            
        self.spec_type = spec_type # 'x', 'y', 'xy', 'circle', 'both'
        
        self.statetype= statetype
        self.actiontype= actiontype
        self.nagents= nagents
        self.nActions = nActions
        
        # Choose reward type function
        #if rewardtype[0] =='k':
        #    order = int(rewardtype[1])
        #    def myreward(self):
        #        return self.rewardk(self.mykrange(order), rewardtype[-1] )
        #elif rewardtype[0:2] == 'ratio':
        #    def mreward(self):
        #        return self.rewardratio()

        # Initialize
        L  = float(Lx); dt = float(dt); tend = float(tend)

        if (nsteps is None):
            nsteps = int(tend/dt)
            nsteps = 10
        else:
            nsteps = int(nsteps)
            # override tend
            tend = dt*nsteps

        print('> tend=',tend,', nsteps=', nsteps, 'NxN',str(NX),'x',str(NY))

        self.case=case
        # -------------------------
        # save to self
        # -------------------------
        # Domain size
        self.Lx     = Lx
        self.Ly     = Ly
        self.NX     = NX
        self.NY     = NY
        # Case parameters
        self.nu     = 1/Re
        self.alpha  = alpha
        self.beta   = beta
        # Time-stepping parameters
        self.dt     = dt
        self.nsteps = nsteps
        # RL Controls
        self.RL     = RL
        # ----------
        self.stepsave = 15000
        print('Init, ---->nsteps=', nsteps)
        # Operators and grid generator
        self.operatorgen()
        # set initial condition
        self.IC()

        self.case = case

	    # SAVE SIZE
        slnU = np.zeros([NX,NNSAVE])
        slnV = np.zeros([NX,NNSAVE])
	    
        Energy = np.zeros([NNSAVE])
        Enstrophy = np.zeros([NNSAVE])
	
        # precompute Gaussians for control:
        if self.RL:
            self.nActions = nActions
            # Action grid
            # self.x = np.arange(self.N)*self.L/(self.N-1)
            self.veRL = 0
            #print('RL to run:', nActions)
   
    def mykrange(self, order):
        NX = int(self.NX)
        kmax = self.kmax
        krange = np.array(range(0, kmax))
        return krange**order
    
    def setup_reference(self):
        NX = self.NX
        kmax = self.kmax       
        rewardtype = self.rewardtype
        spec_type = self.spec_type
        
        if rewardtype == 'enstrophy':
            #print('Enstrophy as reference')
            if spec_type != 'both':
                spec_refx = self.refx_ens[0:kmax,1]
                spec_refy = self.refy_ens[0:kmax,1]
            else:
                spec_ref = self.ref_ens[0:kmax,1]

        elif rewardtype == 'energy':
            #print('Energy as reference')
            if spec_type != 'both':
                spec_refx = self.refx_tke[0:kmax,1]
                spec_refy = self.refy_tke[0:kmax,1]
            else:
                spec_ref = self.ref_tke[0:kmax,1]

        if spec_type != 'both':
            spec_ref = np.vstack((spec_refx,spec_refy))
            self.spec_refx = spec_refx
            self.spec_refy = spec_refy

        self.spec_ref = spec_ref

    def setup_target(self):
        NX = self.NX
        kmax = self.kmax
        rewardtype = self.rewardtype
        spec_type = self.spec_type
        
        if spec_type == 'both':
            if rewardtype == 'enstrophy':
                #print('Enstrophy as reference')
                spec_nowx = self.enstrophy_spectrum(dir_x=2, dir_y=0)
                spec_nowy = self.enstrophy_spectrum(dir_x=0, dir_y=2)
            elif rewardtype == 'energy':
                #print('Energy as reference')
                spec_nowx = self.energy_spectrum(dir_x=2, dir_y=0)
                spec_nowy = self.energy_spectrum(dir_x=0, dir_y=2)

            spec_now = np.vstack((spec_nowx,spec_nowy))   
            self.spec_nowx=spec_nowx
            self.spec_nowy=spec_nowy
            
        elif spec_type == 'xy':
            if rewardtype == 'enstrophy':
                #print('Enstrophy as reference')
                spec_now = self.enstrophy_spectrum(dir_x=1, dir_y=1)
            elif rewardtype == 'energy':
                #print('Energy as reference')
                spec_now = self.energy_spectrum(dir_x=1, dir_y=1)

        self.spec_now=spec_now
        return spec_now

    def setup_reward(self):
        rewardtype = self.rewardtype
        krange = self.krange
        rewardfunc = self.rewardfunc

        reference  = self.spec_ref
        target = self.setup_target()

        if rewardfunc == '1' or rewardfunc == '3':
            myreward = 1/( np.linalg.norm( krange*(target-reference)  )**2 )
            #print(myreward)
        elif rewardfunc == 'c':
            myreward = - np.linalg.norm( (target-reference)  )**2
        elif rewardfunc == 'e':
            myreward = - np.linalg.norm( np.exp( (np.log(target)-np.log(reference))**2) )

        return myreward

    def mySGS(self, action):
        actiontype = self.actiontype
        if actiontype=='CL':
            nu = self.leith_cs(action)
        elif actiontype=='CS':
            nu = self.smag_cs(action)
        return nu

    def step(self, action=None ):
        '''
        2D Turbulence: One time step simulation of 2D Turbulence
        '''
        NX=self.NX

        forcing  = np.zeros(self.nActions)
        if (action is not None):
            #assert len(action) == self.nActions, print("Wrong number of actions. provided: {}, expected:{}".format(len(action), self.nActions))

            forcing = self.upsample(action)
            self.veRL = forcing#forcing[0]# For test
            #print(self.veRL)
            #stop_veRL

        if self.stepnum % self.stepsave == 0:
            print(self.stepnum)
            #self.myplot()
            #savemat('N'+str(self.NX)+'_t='+str(self.stepnum)+'.mat',dict([('psi_hat', self.psi_hat),('w_hat', self.w1_hat)]))
            print('time:', np.round((time.time()-self.tic)/60.0,4),' min.')

        self.stepturb(action)
        self.sol = [self.w1_hat, self.psiCurrent_hat, self.psiPrevious_hat]
        self.stepnum += 1
        self.t       += self.dt
   

    def simulate(self, nsteps=None):
        nsteps= self.nsteps
        # advance in time for nsteps steps
        for n in range(1, nsteps+1):
            self.step()

    def state(self):
        NX= int(self.NX)
        kmax= self.kmax
        statetype= self.statetype
        nagents= self.nagents
        # --------------------------------------
        STATE_GLOBAL=True
        # --------------------------------------
        if statetype=='psiomegadiag':
            s1= np.diag(np.real(np.fft.ifft2(self.w1_hat))).reshape(-1,)
            s2= np.diag(np.real(np.fft.ifft2(self.psiCurrent_hat))).reshape(-1,)
            mystate= np.hstack((s1,s2))
        # --------------------------
        elif statetype=='enstrophy':
            enstrophy= self.enstrophy_spectrum()
            mystate= np.log(enstrophy[0:kmax])
        # --------------------------
        elif statetype=='energy':
            energy= self.energy_spectrum()
            mystate= np.log(energy[0:kmax])
        # --------------------------
        elif statetype=='psiomega':
           '''
           self.sol = [self.w1_hat, self.psiCurrent_hat, self.psiPrevious_hat]

           '''
           STATE_GLOBAL=False
           s1 = np.real(np.fft.ifft2(self.sol[0])) #w1
           s2 = np.real(np.fft.ifft2(self.sol[1])) #psi
        # --------------------------
        elif statetype=='omega':
           '''
           self.sol = [self.w1_hat, self.psiCurrent_hat, self.psiPrevious_hat]

           '''
           STATE_GLOBAL=False
           s1 = np.real(np.fft.ifft2(self.sol[0])) #w1
        # --------------------------
        elif statetype=='psiomegalocal':
           STATE_GLOBAL=False
           s1 = np.real(np.fft.ifft2(self.sol[0])) #w1
           s2 = np.real(np.fft.ifft2(self.sol[1])) #psi
        # --------------------------
        elif statetype=='invariantlocal':
           STATE_GLOBAL=False
           #s1 = np.real(np.fft.ifft2(self.sol[0])) #w1
           s2 = np.real(np.fft.ifft2(self.sol[1])) #psi
        # --------------------------
        elif statetype=='invariantlocalandglobalgradgrad': #eps':
           STATE_GLOBAL=False
           #s1 = np.real(np.fft.ifft2(self.sol[0])) #w1
           s2 = np.real(np.fft.ifft2(self.sol[1])) #psi
           enstrophy= self.enstrophy_spectrum()
           mystateglobal = np.log(enstrophy[0:kmax])

        if STATE_GLOBAL:
            mystatelist = [mystate.tolist()]
            for _ in range(nagents-1):
                mystatelist.append(mystate.tolist())

        elif not STATE_GLOBAL:
            if statetype=='psiomega':
                mystatelist1 =  split2d(s1, self.nActiongrid)
                mystatelist2 =  split2d(s2, self.nActiongrid)
                mystatelist = [x+y for x,y in zip(mystatelist1, mystatelist2)]
            elif statetype=='omega':
                mystatelist =  split2d(s1, self.nActiongrid)
            elif statetype=='psiomegalocal':
                NX = self.NX
                NY = self.NY
                mystatelist1 =  pickcenter(s1, NX, NY, self.nActiongrid)
                mystatelist2 =  pickcenter(s2, NY, NY, self.nActiongrid)
                mystatelist = [x+y for x,y in zip(mystatelist1, mystatelist2)]
            elif statetype=='invariantlocal':
                NX = self.NX
                NY = self.NY
                Kx = self.Kx
                Ky = self.Ky

                psi_hat = self.sol[1]

                u1_hat, v1_hat = self.psi_2_uv(psi_hat, Kx, Ky)

                dudx_hat = self.D_dir(u1_hat,Kx)
                dudy_hat = self.D_dir(u1_hat,Ky)

                dvdx_hat = self.D_dir(v1_hat,Kx)
                dvdy_hat = self.D_dir(v1_hat,Ky)
                
                dudxx_hat = self.D_dir(dudx_hat,Kx)
                dudxy_hat = self.D_dir(dudx_hat,Ky)

                dvdyx_hat = self.D_dir(dvdy_hat,Kx)
                dvdyy_hat = self.D_dir(dvdy_hat,Ky)


                dudx = np.fft.ifft2(dudx_hat).real
                dudy = np.fft.ifft2(dudy_hat).real
                dvdx = np.fft.ifft2(dvdx_hat).real
                dvdy = np.fft.ifft2(dvdy_hat).real

                dudxx = np.fft.ifft2(dudxx_hat).real
                dudxy = np.fft.ifft2(dudxy_hat).real
                dvdyx = np.fft.ifft2(dvdyx_hat).real
                dvdyy = np.fft.ifft2(dvdyy_hat).real


                list1 =  pickcenter(dudx, NX, NY, self.nActiongrid)
                list2 =  pickcenter(dudy, NX, NY, self.nActiongrid)
                list3 =  pickcenter(dvdx, NX, NY, self.nActiongrid)
                list4 =  pickcenter(dvdy, NX, NY, self.nActiongrid)
                
                list5 =  pickcenter(dudxx, NX, NY, self.nActiongrid)
                list6 =  pickcenter(dudxy, NX, NY, self.nActiongrid)
                list7 =  pickcenter(dvdyx, NX, NY, self.nActiongrid)
                list8 =  pickcenter(dvdyy, NX, NY, self.nActiongrid)

                mystatelist = []
                for dudx,dudy,dvdx,dvdy,dudxx,dudxy,dvdyx,dvdyy in zip(list1, list2, list3, list4, list5, list6, list7, list8):
                    gradV = np.array([[dudx[0], dudy[0]],
                                      [dvdx[0], dvdy[0]]])
                    hessV = np.array([[dudxx[0], dudxy[0]],
                                      [dvdyx[0], dvdyy[0]]])
                    allinvariants = self.invariant(gradV)+self.invariant(hessV)
                    mystatelist.append(allinvariants)
                    
            elif statetype=='invariantlocalandglobalgradgrad':#eps':
                NX = self.NX
                NY = self.NY
                Kx = self.Kx
                Ky = self.Ky

                psi_hat = self.sol[1]

                u1_hat, v1_hat = self.psi_2_uv(psi_hat, Kx, Ky)
                
                dudx_hat = self.D_dir(u1_hat,Kx)
                dudy_hat = self.D_dir(u1_hat,Ky)

                dvdx_hat = self.D_dir(v1_hat,Kx)
                dvdy_hat = self.D_dir(v1_hat,Ky)
                
                dudxx_hat = self.D_dir(dudx_hat,Kx)
                dudyy_hat = self.D_dir(dudy_hat,Ky)

                dvdxx_hat = self.D_dir(dvdx_hat,Kx)
                dvdyy_hat = self.D_dir(dvdy_hat,Ky)


                dudx = np.fft.ifft2(dudx_hat).real
                dudy = np.fft.ifft2(dudy_hat).real
                dvdx = np.fft.ifft2(dvdx_hat).real
                dvdy = np.fft.ifft2(dvdy_hat).real

                dudxx = np.fft.ifft2(dudxx_hat).real
                dudyy = np.fft.ifft2(dudyy_hat).real
                dvdxx = np.fft.ifft2(dvdxx_hat).real
                dvdyy = np.fft.ifft2(dvdyy_hat).real

                #mystateglobaleps = np.sum(np.sum( np.power(dudx,2)+np.power(dvdy,2)))

                list1 =  pickcenter(dudx, NX, NY, self.nActiongrid)
                list2 =  pickcenter(dudy, NX, NY, self.nActiongrid)
                list3 =  pickcenter(dvdx, NX, NY, self.nActiongrid)
                list4 =  pickcenter(dvdy, NX, NY, self.nActiongrid)
                
                list5 =  pickcenter(dudxx, NX, NY, self.nActiongrid)
                list6 =  pickcenter(dudyy, NX, NY, self.nActiongrid)
                list7 =  pickcenter(dvdxx, NX, NY, self.nActiongrid)
                list8 =  pickcenter(dvdyy, NX, NY, self.nActiongrid)

                mystatelist = []
                for dudx,dudy,dvdx,dvdy, dudxx,dudyy,dvdxx,dvdyy in zip(list1, list2, list3, list4, list5, list6, list7, list8):
                    gradV = np.array([[dudx[0], dudy[0]],
                                      [dvdx[0], dvdy[0]]])
                    gradgradV = np.array([[dudxx[0], dvdxx[0]],
                                         [dudyy[0], dvdyy[0]]])
                    
                    allinvariants = self.invariant(gradV)+self.invariant(gradgradV)+mystateglobal.tolist()#+mystateglobaleps.tolist()
                    mystatelist.append(allinvariants)
                    
        if mystatelist[0][0]>1000: raise Exception("State diverged!")
        return mystatelist

    def reward(self):
        nagents=self.nagents
        # --------------------------------------
        try:
            myreward=self.setup_reward()
        except:
            myreward=-10000
        # --------------------------
        myrewardlist = [myreward.tolist()]
        for _ in range(nagents-1):
            myrewardlist.append(myreward.tolist())
        return myrewardlist 

    def convection_conserved(self, psiCurrent_hat, w1_hat):
        '''
        second-order Adams–Bashforth for the nonlinear term
        J()
        '''
        Kx = self.Kx
        Ky = self.Ky
        
        # Velocity
        u_hat, v_hat = self.psi_2_uv(psiCurrent_hat, Kx, Ky)
        # Convservative form
        w1 = np.real(np.fft.ifft2(w1_hat))
        conu1 = 1j*Kx*np.fft.fft2((np.real(np.fft.ifft2(u_hat))*w1))
        conv1 = 1j*Ky*np.fft.fft2((np.real(np.fft.ifft2(v_hat))*w1))
        convec_hat = conu1 + conv1
     
        # Non-conservative form
        w1x_hat = 1j*Kx*w1_hat
        w1y_hat = 1j*Ky*w1_hat
        conu1 = np.fft.fft2(np.real(np.fft.ifft2(u_hat))*np.real(np.fft.ifft2(w1x_hat)))
        conv1 = np.fft.fft2(np.real(np.fft.ifft2(v_hat))*np.real(np.fft.ifft2(w1y_hat)))
        convecN_hat = conu1 + conv1
  
        convec_hat = 0.5*(convec_hat + convecN_hat)
        return convec_hat

    def psi_2_uv(self, psi_hat, Kx, Ky):
        u_hat = 1j* Ky * psi_hat
        v_hat = -1j * Kx * psi_hat
        return u_hat, v_hat

    def stepturb(self, action):
        #psiCurrent_hat = self.psiCurrent_hat
        #w1_hat = self.w1_hat
        Ksq = self.Ksq
        Kx = self.Kx
        Ky = self.Ky
        invKsq = self.invKsq
        dt = self.dt
        nu = self.nu
        alpha = self.alpha
        beta = self.beta
        Fk_hat = self.Fk_hat
        # ---------------
        psiCurrent_hat = self.psiCurrent_hat
        w1_hat = self.w1_hat
        convec0_hat = self.convec1_hat
        # 2 Adam bash forth Crank Nicolson
        convec1_hat = self.convection_conserved(psiCurrent_hat, w1_hat)
        diffu_hat = -Ksq*w1_hat
       
        # Calculate SGS diffusion 
        ve = self.mySGS(action)
              
        # ----------------------------#|
        # Calculate the PI term for local: ∇×∇.(-2 ν_e S_{ij} )
        Tau11, Tau12, Tau22 = Tau_eddy_viscosity(ve, psiCurrent_hat, Kx, Ky)
        
        Tau11_hat = np.fft.fft2(Tau11)
        Tau12_hat = np.fft.fft2(Tau12)
        Tau22_hat = np.fft.fft2(Tau22)
        
        PiOmega_hat = Tau2PiOmega_2DFHIT(Tau11_hat, Tau12_hat, Tau22_hat, Kx, Ky, spectral=True)
        # pass to self ---------------#|
        self.PiOmega_hat = PiOmega_hat#| 
        # ----------------------------#|
        # AB2 for Jacobian term
        convec_hat = 1.5*convec1_hat - 0.5*convec0_hat
        # RHS: + Jacobian term + Forcing + SGS model
        # --- Euler for SGS term (Π)
        RHS = w1_hat - dt*convec_hat + dt*0.5*nu*diffu_hat - dt*(Fk_hat+PiOmega_hat) #+ dt*beta*V1_hat : Last term moved below

        # --- β case: Coriolis (Beta case)
        v_hat = -(1j*Kx)*psiCurrent_hat
        # RHS + Coriolis
        RHS = RHS + dt*beta*v_hat # Beta-case: Coriolis

        #psiTemp = RHS/(1+dt*alpha+0.5*dt*(nu+ve)*Ksq)
        psiTemp = RHS/(1+dt*alpha+0.5*dt*nu*Ksq)
    
        w0_hat = w1_hat
        w1_hat = psiTemp
        convec0_hat = convec1_hat

        # Poisson equation for Psi
        psiPrevious_hat = psiCurrent_hat
        psiCurrent_hat = -w1_hat*invKsq

        # Update this step
        self.update(w0_hat, w1_hat, convec0_hat, convec1_hat, psiPrevious_hat, psiCurrent_hat, ve )

    def update(self, w0_hat, w1_hat, convec0_hat, convec1_hat, psiPrevious_hat, psiCurrent_hat, ve):
        # write to self
        self.w0_hat = w0_hat
        self.w1_hat = w1_hat
        self.convec0_hat = convec0_hat
        self.convec1_hat = convec1_hat # it is never used, consider deleting 
        self.psiPrevious_hat = psiPrevious_hat
        self.psiCurrent_hat = psiCurrent_hat
        self.ve = ve
        #self.velist.append(self.veRL)
        self.myrewardlist=[]
        self.mystatelist=[]

    def IC(self, u0=None, v0=None, SEED=42):
        X = self.X
        Y = self.Y
        NX = self.NX
        NY = self.NY
        Kx = self.Kx
        Ky = self.Ky
        invKsq = self.invKsq
        # ------------------
        np.random.seed(SEED)
        # ------------------
        # Forcing
        if self.case=='1':
            # kappaf = 4
            fkx, fky = 4, 4
            beta = 0.0
        elif self.case=='2':
            # kappaf = 4
            fkx, fky = 4, 4
            beta = 20.0
        elif self.case=='4':
            # kappaf = 
            fkx, fky = 25, 25
            beta = 0.0

        # Deterministic forcing in Physical space
        Fk = fky * np.cos(fky * Y) + fkx * np.cos(fkx * X)

        # Deterministic forcing in Fourier space
        Fk_hat = np.fft.fft2(Fk)
        #
        time = 0.0
        slnW = []
        
        if self.case =='1':
            folder_path = '_init/Re20kf4/iniWor_Re20kf4_'
        elif self.case =='2':
            folder_path = '_init/Re20kf4beta20/iniWor_Re20kf4beta20_'
        elif self.case =='4':
            folder_path = '_init/Re20kf25/iniWor_Re20kf25_'

        filenum_str=str(1)
        data_Poi = loadmat(folder_path+str(NX)+'_'+filenum_str+'.mat')
        w1 = data_Poi['w1']
        

        spec_type = self.spec_type
        if self.case =='4':
            spec_type =='xy'
            ref_tke = np.loadtxt("_init/Re20kf25/energy_spectrum_Re20kf25_DNS1024_xy.dat")
            ref_ens = np.loadtxt("_init/Re20kf25/enstrophy_spectrum_Re20kf25_DNS1024_xy.dat")
        if self.case == '2':
        #    spec_type = self.spec_type
            print('Loading spectra, spectra type: ',spec_type)
            if spec_type == 'both':
                refx_tke = np.loadtxt("_init/Re20kf4beta20/energy_spectrum_Re20kf4beta20_DNS1024_x.dat")
                refx_ens = np.loadtxt("_init/Re20kf4beta20/enstrophy_spectrum_Re20kf4beta20_DNS1024_x.dat")
                refy_tke = np.loadtxt("_init/Re20kf4beta20/energy_spectrum_Re20kf4beta20_DNS1024_y.dat")
                refy_ens = np.loadtxt("_init/Re20kf4beta20/enstrophy_spectrum_Re20kf4beta20_DNS1024_y.dat")
                self.refx_tke=refx_tke
                self.refx_ens=refx_ens
                self.refy_tke=refy_tke
                self.refy_ens=refy_ens
            #else:
            print('..., averaged in x-y directions')
            ref_tke = np.loadtxt("_init/Re20kf4beta20/energy_spectrum_Re20kf4beta20_DNS1024_xy"+".dat")
            ref_ens = np.loadtxt("_init/Re20kf4beta20/enstrophy_spectrum_Re20kf4beta20_DNS1024_xy"+".dat")

        if self.case == '1':
            spec_type =='xy'
            ref_tke = np.loadtxt("_init/Re20kf4/energy_spectrum_DNS1024_xy.dat")
            ref_ens = np.loadtxt("_init/Re20kf4/enstrophy_spectrum_DNS1024_xy.dat")

        '''
        if spec_type =='x':
            DIR_X, DIR_Y = 2, 0
        elif spec_type =='y':
            DIR_X, DIR_Y = 0, 2
        elif spec_type =='xy':
            DIR_X, DIR_Y = 1, 1
        else:
            print(spec_type, ' not implemented')

        self.DIR_X, self.DIR_Y = DIR_X, DIR_Y
        '''
        self.spec_type = spec_type
        
        w1_hat = np.fft.fft2(w1)
        psiCurrent_hat = -invKsq*w1_hat
        psiPrevious_hat = psiCurrent_hat
    
        # ... and save to self
        self.w1_hat = w1_hat
        self.psiCurrent_hat = psiCurrent_hat
        self.psiPrevious_hat = psiPrevious_hat
        self.psi_hat = psiCurrent_hat

        self.t = 0.0
        self.stepnum = 0
        self.sol = [self.w1_hat, self.psiCurrent_hat, self.psiPrevious_hat]
        # 
        convec0_hat = self.convection_conserved(psiCurrent_hat, w1_hat)
        self.convec0_hat = convec0_hat
        self.convec1_hat = convec0_hat
        # 
        self.Fk_hat = Fk_hat
        self.Fn = fkx # Forcing k: used in plotting, for x/y-dirc spectrum use fkx, fky, for radially averaged power spectral: (fkx**2+fky**2)**0.5
        self.beta = beta # Coriolis β
        # Aux reward 
        kmax = self.kmax
        krange = np.array(range(0, kmax))
        self.krange = krange
        # SGS Model
        self.ve = 0
        #self.velist = []
        # Reference files 
        self.ref_tke = ref_tke
        self.ref_ens = ref_ens
        # temporary
        self.N = NX
        self.L = 2*np.pi
        # 
        self.setup_reference()
        self.setup_MAagents()

    def setup_MAagents(self):
        # Copied from:   f36df60 on main  
        # temporary
        nActiongrid = int((self.nActions*self.nagents)**0.5)
        self.nActiongrid = nActiongrid
        # Initlize action
        # endpoints are repeated left column and bottow row, using np.pad(A, 1, mode='wrap')[1:,1:]
        X = np.linspace(0,self.L,nActiongrid+1, endpoint=True)
        Y = np.linspace(0,self.L,nActiongrid+1, endpoint=True)
        self.xaction = X
        self.yaction = Y

    def upsample(self, action, degree=2): 
        action_flat = [item for sublist in action for item in sublist]
        arr_action = np.array(action_flat).reshape(self.nActiongrid, self.nActiongrid)
        # repeating left column on right, and bottom row on top
        arr_action = np.pad(arr_action, 1, mode='wrap')[1:,1:]
        upsample_action = RectBivariateSpline(self.xaction, self.yaction, arr_action, kx=degree, ky=degree)

        # Initlize action
        upsamplesize = self.NX # 1 for testing, will be changed to grid size eventually
        x2 = np.linspace(0,self.L, upsamplesize, endpoint=True)
        y2 = np.linspace(0,self.L,  upsamplesize, endpoint=True)
        forcing = upsample_action(x2, y2)
        return forcing

    def operatorgen(self):
        Lx, Ly = self.Lx, self.Ly
        NX, NY = self.NX, self.NY
        dx, dy = Lx/NX, Ly/NY

        # cherry-picked from : envfluids/Py2D: 09e0208
        INDEXING = 'ij'
        # Create an array of x-coordinates, ranging from 0 to (Lx - dx)
        x = np.linspace(0, Lx - dx, num=NX)
        y = np.linspace(0, Lx - dx, num=NY)

        # Create 2D arrays of the x and y-coordinates using a meshgrid.
        X, Y = np.meshgrid(x, y, indexing=INDEXING)
        #-----------------  
        # Create an array of the discrete Fourier Transform sample frequencies in x-direction
        kx = 2 * np.pi * np.fft.fftfreq(NX, d=dx)
        # Create an array of the discrete Fourier Transform sample frequencies in y-direction
        ky = 2 * np.pi * np.fft.fftfreq(NX, d=dx)
        # Return coordinate grids (2D arrays) for the x and y wavenumbers
        (Kx, Ky) = np.meshgrid(kx, ky, indexing=INDEXING)

        Ksq      = Kx**2 + Ky**2
        Kabs     = np.sqrt(Ksq)

        Ksq[0,0] = 1e12
        invKsq   = 1.0/Ksq
        Ksq[0,0] = 0
        invKsq[0,0] = 0

        kmax = int(NX/2)
	    # .... and save to self
        self.X = X
        self.Y = Y
        self.dx = dx
        self.kx = kx
        self.Ky = Ky
        self.Kx = Kx
        self.Ksq = Ksq
        self.Kabs = Kabs
        self.invKsq = invKsq
        self.kmax = kmax
    #-----------------------------------------
    # ============= SGS Models ===============
    #-----------------------------------------
    def leith_cs(self, action=None):
        '''
        ve =(Cl * \delta )**3 |Grad omega|  LAPL omega ; LAPL := Grad*Grad
        '''
        #print('action is:', action_leith)
        if action != None:
        #    if self.veRL !=0:
            CL3 = self.veRL#action_leith[0]
        else:
            CL3 = 0.17**3# (Lit)
        #else:
        Kx = self.Kx
        Ky = self.Ky
        w1_hat = self.w1_hat

        w1x_hat = -(1j*Kx)*w1_hat
        w1y_hat = (1j*Ky)*w1_hat
        w1x = np.real(np.fft.ifft2(w1x_hat))
        w1y = np.real(np.fft.ifft2(w1y_hat))
        abs_grad_omega = np.mean(np.sqrt( w1x**2+w1y**2  ))
        # 
        delta3 = (2*np.pi/self.NX)**3
        ve = CL3*delta3*abs_grad_omega
        return ve

    def smag_cs(self, action=None):
        Kx = self.Kx
        Ky = self.Ky
        NX = self.NX
        psiCurrent_hat = self.psiCurrent_hat
        w1_hat = self.w1_hat

        if action != None:
            cs = (self.veRL) * ((2*np.pi/NX )**2)  # for LX = 2 pi
        else:
            #self.veRL = 0.17 * 2
            #cs = (self.veRL) * ((2*np.pi/NX )**2)  # for LX = 2 pi
            cs = (0.17 * 2*np.pi/NX )**2  # for LX = 2 pi

        S1 = np.real(np.fft.ifft2(-Ky*Kx*psiCurrent_hat)) # make sure .* 
        S2 = 0.5*np.real(np.fft.ifft2(-(Kx*Kx - Ky*Ky)*psiCurrent_hat))
        S  = 2.0*(S1*S1 + S2*S2)**0.5
#        cs = (0.17 * 2*np.pi/NX )**2  # for LX = 2 pi
        S = (np.mean(S**2.0))**0.5;
        ve = cs*S
        return ve
    #-----------------------------------------
    def enstrophy_spectrum(self, dir_x=1, dir_y=1):
        NX = self.NX
        NY = self.NY # Square for now
        w1_hat = self.w1_hat
        #-----------------------------------
        signal = np.power(abs(w1_hat),2)/2;

        spec_x = np.mean(np.abs(signal),axis=0)
        spec_y = np.mean(np.abs(signal),axis=1)
        spec = (dir_x*spec_x + dir_y*spec_y)/2
        spec = spec/ (NX**2)/NX
        spec = spec[0:int(NX/2)]

        arr_len = int(NX/2)
        kplot = np.array(range(arr_len))
    
        self.enstrophy_spec = spec
        return spec
    #-----------------------------------------
    def energy_spectrum(self, dir_x=1, dir_y=1):
        NX = self.NX
        NY = self.NY # Square for now
        Ksq = self.Ksq
        w1_hat = self.w1_hat
    
        Ksq[0,0]=1
        w_hat = np.power(np.abs(w1_hat),2)/NX/NY/Ksq
        w_hat[0,0]=0;
        spec_x = np.mean(np.abs(w_hat),axis=0)
        spec_y = np.mean(np.abs(w_hat),axis=1)
        spec = (dir_x*spec_x + dir_y*spec_y)/2
        spec = spec /NX
        
        spec=spec[0:int(NX/2)]
        return  spec
    #-----------------------------------------
    def myplot(self, append_str='', prepend_str=''):
        NX = int(self.NX)
        Kplot = self.Kx; kplot_str = '\kappa_{x}'; kmax = self.kmax
        #Kplot = self.Kabs; kplot_str = '\kappa_{sq}'; kmax = int(np.sqrt(2)*NX/2)+1
        #kplot_str = '\kappa_{sq}'
        stepnum = self.stepnum
        ve = self.ve
        Fn = self.Fn
        dt = self.dt
        # --------------
        energy = self.energy_spectrum()
        enstrophy = self.enstrophy_spectrum()
        #
        #spec_nowx = self.spec_nowx
        #spec_refx = self.spec_refx
        #spec_nowy = self.spec_nowy
        #spec_refy = self.spec_refy
        #
        plt.figure(figsize=(8,14))
 
        omega = np.real(np.fft.ifft2(self.sol[0]))
        VMAX, VMIN = np.max(omega), np.min(omega)
        VMAX = max(np.abs(VMIN), np.abs(VMAX))
        VMIN = -VMAX
        levels = np.linspace(VMIN,VMAX,100)

        ax = plt.subplot(3,2,1)
        plt.contourf(omega, levels, vmin=VMIN, vmax=VMAX); plt.colorbar()
        plt.title(r'$\omega$')
        ax.set_aspect('equal', adjustable='box')

        psi = np.real(np.fft.ifft2(self.sol[1]))
        VMAX, VMIN = np.max(psi), np.min(psi)
        VMAX = max(np.abs(VMIN), np.abs(VMAX))
        VMIN = -VMAX
        levels = np.linspace(VMIN,VMAX,100)
 
        ax = plt.subplot(3,2,2)
        plt.contourf(psi, levels, vmin=VMIN, vmax=VMAX); plt.colorbar()
        plt.title(r'$\psi$')
        ax.set_aspect('equal', adjustable='box')

        ref_tke = self.ref_tke#np.loadtxt("tke.dat")
        # Energy 
        plt.subplot(3,2,3)
        energy = self.energy_spectrum()
        plt.loglog(Kplot[0:kmax,0], energy[0:kmax],'k')
        plt.plot([self.Fn,self.Fn],[1e-6,1e6],':k', alpha=0.5, linewidth=2)
        plt.plot(ref_tke[:,0],ref_tke[:,1],':k', alpha=0.25, linewidth=4)
               
        plt.title(r'$\hat{E}$'+rf'$({kplot_str})$')
        plt.xlabel(rf'${kplot_str}$')
        plt.xlim([1,1e3])
        plt.ylim([1e-6,1e1])#plt.ylim([1e-6,1e0])
        
        ref_ens = self.ref_ens#np.loadtxt("ens.dat")
        # Enstrophy
        plt.subplot(3,2,4)
        enstrophy = self.enstrophy_spectrum()
        plt.plot([self.Fn,self.Fn],[1e-6,1e6],':k', alpha=0.5, linewidth=2)
        plt.plot(ref_ens[:,0],ref_ens[:,1],':k', alpha=0.25, linewidth=4)
        plt.loglog(Kplot[0:kmax,0], enstrophy[0:kmax],'k')
        plt.title(rf'$\varepsilon({kplot_str})$')
        plt.xlabel(rf'${kplot_str}$')
        plt.xlim([1,1e2])
        #plt.ylim([1e-5,1e0])
        plt.ylim([1e-3,1e1])
        #plt.pcolor(np.real(sim.w1_hat));plt.colorbar()
        
        if self.rewardtype=='energy':
            plt.subplot(3,2,3)
        else:
            plt.subplot(3,2,4)
        '''   
        plt.loglog(Kplot[0:kmax,0], spec_nowx,'-.r')
        plt.loglog(Kplot[0:kmax,0], spec_refx,'-r', alpha=0.5)
        plt.loglog(Kplot[0:kmax,0], spec_nowy,'-.c')
        plt.loglog(Kplot[0:kmax,0], spec_refy,'-c', alpha=0.5)
        '''
        #plt.subplot(3,2,5)
        #omega = np.real(np.fft.ifft2(self.w1_hat))
        #Vecpoints, exp_log_kde, log_kde, kde = self.KDEof(omega)
        #plt.semilogy(Vecpoints,exp_log_kde)  
        #plt.xlabel(r'$\omega$')
        #plt.ylabel('PDF')
        #plt.title('$t=$'+f"{stepnum*dt:.2E}"+r'$, \nu=$'+f"{ve:.2E}")
 

        Kx = self.Kx
        Ky = self.Ky
        psi_hat = self.psiCurrent_hat
        v_hat = -(1j*Kx)*psi_hat
        u_hat = (1j*Ky)*psi_hat
        u = np.real(np.fft.ifft2(u_hat))
        v = np.real(np.fft.ifft2(v_hat))

        plt.subplot(3,2,5)
        plt.pcolor(u)
        plt.subplot(3,2,6)
        plt.pcolor(v)
        plt.title('v')
        plt.colorbar()
        #plt.subplot(3,2,6)
        #plt.semilogy(Vecpoints,log_kde) 
        filename = prepend_str+'2Dturb_'+str(stepnum)+append_str
        plt.savefig(filename+'.png', bbox_inches='tight', dpi=450)
        plt.close('all')
#        print(filename)
#        print(Kplot[0:kmax,0].shape)
#        print( energy[0:kmax].shape)
#        print( np.stack((Kplot[0:kmax,0], energy[0:kmax]),axis=0).T.shape   )
        np.savetxt(filename+'_tke.out', np.stack((Kplot[0:kmax,0], energy[0:kmax]),axis=0).T, delimiter='\t')
        np.savetxt(filename+'_ens.out', np.stack((Kplot[0:kmax,0], enstrophy[0:kmax]),axis=0).T, delimiter='\t')

    #-----------------------------------------
    def myplotforcing(self, append_str='', prepend_str=''):
        NX = int(self.NX)
        Kx = self.Kx
        Ky = self.Ky
        w1_hat = self.w1_hat
        omega = np.real(np.fft.ifft2(self.sol[0]))
        w1x_hat = -(1j*Kx)*w1_hat
        w1y_hat = (1j*Ky)*w1_hat
        w1x = np.real(np.fft.ifft2(w1x_hat))
        w1y = np.real(np.fft.ifft2(w1y_hat))
        grad_omega = np.sqrt( w1x**2+w1y**2)

        veRL=self.veRL
        stepnum = self.stepnum

        plt.figure(figsize=(8,14))
        levels = np.linspace(-30,30,100)

        plt.subplot(3,2,1)
        plt.contourf(veRL)
        plt.colorbar()
        plt.title(r'forcing')

        plt.subplot(3,2,3)
        plt.contourf(grad_omega)
        plt.colorbar()
        plt.title(r'$\nabla \omega$')

        plt.subplot(3,2,2)
        xplot = veRL.reshape(-1,1)
        yplot = omega.reshape(-1,1)

        xv, yv, rv, pos, meanxy = self.multivariat_fit(xplot,yplot)
        plt.plot(xplot, yplot,'.k',alpha=0.5)
        plt.scatter(meanxy[0],meanxy[1], marker="+", color='red',s=100)
        plt.contour(xv, yv, rv.pdf(pos))

        plt.xlabel(r'$forcing$')
        plt.ylabel(r'$\omega$')
        plt.grid(color='gray', linestyle='dashed')

        plt.subplot(3,2,4)
        xplot = veRL.reshape(-1,1)
        yplot = grad_omega.reshape(-1,1)
        xv, yv, rv, pos, meanxy = self.multivariat_fit(xplot,yplot)
        plt.plot(xplot, yplot,'.k',alpha=0.5)
        plt.scatter(meanxy[0],meanxy[1], marker="+", color='red',s=100)
        plt.contour(xv, yv, rv.pdf(pos))

        plt.xlabel(r'$forcing$')
        plt.ylabel(r'$\nabla \omega$')
        plt.grid(color='gray', linestyle='dashed')

        PiOmega_hat = self.PiOmega_hat#| 
        PiOmega = np.fft.ifft2(PiOmega_hat).real
        VMIN = np.min(np.min(PiOmega))
        VMAX = np.max(np.max(PiOmega))
        plt.subplot(3,2,5)
        plt.contourf(PiOmega,levels=21)#, vmin=VMIN, vmax=VMAX) 
        plt.colorbar()
        plt.title(r'$\Pi = \nabla .( \nu \nabla \omega)$')

        filename = prepend_str+'2Dturb_'+str(stepnum)+'forcing'+append_str
        plt.savefig(filename+'.png', bbox_inches='tight', dpi=450)
        plt.close('all')
    #-----------------------------------------  
    def multivariat_fit(self, x, y):
        covxy = np.cov(x,y, rowvar=False)
        meanxy=np.mean(x),np.mean(y)
        rv = multivariate_normal(mean=meanxy, cov=covxy, allow_singular=False)
        xv, yv = np.meshgrid(np.linspace(x.min(),x.max(),50), 
                             np.linspace(y.min(),y.max(),50), indexing='ij')
        pos = np.dstack((xv, yv))

        return xv, yv, rv, pos, meanxy 
    #-----------------------------------------
    def KDEof(self, u):
        from PDE_KDE import myKDE
        Vecpoints, exp_log_kde, logkde, kde = myKDE(u)
        return Vecpoints, exp_log_kde, logkde, kde
    #-----------------------------------------
    def D_dir(self, u_hat, K_dir):
        Du_Ddir = 1j*K_dir*u_hat
        return Du_Ddir  
    #-----------------------------------------
    def decompose_sym(self, A):
        S = 0.5*(A+A.T)
        R = 0.5*(A-A.T)
        return S, R
    #-----------------------------------------
    def invariant(self, A):
        S, R = self.decompose_sym(A)
        lambda1 = np.trace(S)
        lambda2 = np.trace(S@S)
        lambda3 = np.trace(R@R)
        return [lambda1, lambda2, lambda3]
